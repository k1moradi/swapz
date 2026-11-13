#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
#include <stddef.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define SWAPZ_REPLAY_PAGE_BYTES 4096U
#define SWAPZ_REPLAY_MAX_QD 32U
#define SWAPZ_REPLAY_PLAN_HEADER_BYTES 16U

/* The producer serializes this private ABI explicitly in little-endian. */
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "native replay plan requires a little-endian target"
#endif

struct replay_event {
	uint32_t page;
	uint32_t fixture;
	uint8_t lane;
	uint8_t phase;
	char op;
	uint8_t reserved;
};

_Static_assert(sizeof(struct replay_event) == 12,
	       "native plan event must occupy exactly 12 bytes");
_Static_assert(offsetof(struct replay_event, page) == 0 &&
	       offsetof(struct replay_event, fixture) == 4 &&
	       offsetof(struct replay_event, lane) == 8 &&
	       offsetof(struct replay_event, phase) == 9 &&
	       offsetof(struct replay_event, op) == 10 &&
	       offsetof(struct replay_event, reserved) == 11,
	       "native plan event layout does not match the Python producer");

/* Fixed 16-byte little-endian latency record, zero-padded from calloc. */
struct replay_latency {
	char op;
	uint8_t reserved[7];
	uint64_t ns;
};

_Static_assert(sizeof(struct replay_latency) == 16 &&
	       offsetof(struct replay_latency, op) == 0 &&
	       offsetof(struct replay_latency, reserved) == 1 &&
	       offsetof(struct replay_latency, ns) == 8,
	       "native latency result layout does not match Python consumer");

enum replay_mode {
	REPLAY_WAVES = 0,
	REPLAY_PERSISTENT = 1,
};

struct replay_context {
	int device_fd;
	int result_fd;
	const uint8_t *fixture;
	size_t fixture_pages;
	struct replay_event *events;
	struct replay_latency *latencies;
	size_t event_count;
	size_t warmup_ops;
	size_t measure_ops;
	unsigned int qd;
	enum replay_mode mode;
	pthread_barrier_t wave_barrier;
	pthread_barrier_t ready_barrier;
	pthread_barrier_t start_barrier;
	pthread_barrier_t done_barrier;
	atomic_int error_code;
};

struct replay_worker {
	struct replay_context *ctx;
	unsigned int lane;
	uint8_t *read_page;
};

static uint64_t monotonic_ns(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
		return 0;
	return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static uint64_t timeval_us(const struct timeval *tv)
{
	return (uint64_t)tv->tv_sec * 1000000ULL + (uint64_t)tv->tv_usec;
}

static void note_error(struct replay_context *ctx, int error, const char *what)
{
	int expected = 0;

	if (error <= 0)
		error = EIO;
	if (atomic_compare_exchange_strong(&ctx->error_code, &expected, error))
		dprintf(STDERR_FILENO, "io-replay-native: %s: %s\n", what,
			strerror(error));
}

static ssize_t retry_pread(int fd, void *buffer, size_t bytes, off_t offset)
{
	ssize_t result;

	do {
		result = pread(fd, buffer, bytes, offset);
	} while (result < 0 && errno == EINTR);
	return result;
}

static ssize_t retry_pwrite(int fd, const void *buffer, size_t bytes, off_t offset)
{
	ssize_t result;

	do {
		result = pwrite(fd, buffer, bytes, offset);
	} while (result < 0 && errno == EINTR);
	return result;
}

static void replay_one(struct replay_worker *worker, size_t index, bool measured)
{
	struct replay_context *ctx = worker->ctx;
	const struct replay_event *event = &ctx->events[index];
	const uint8_t *expected;
	off_t offset;
	uint64_t start_ns, end_ns;
	ssize_t bytes;

	if (atomic_load(&ctx->error_code))
		return;
	expected = ctx->fixture + (size_t)event->fixture * SWAPZ_REPLAY_PAGE_BYTES;
	offset = (off_t)((uint64_t)event->page * SWAPZ_REPLAY_PAGE_BYTES);
	start_ns = monotonic_ns();
	if (!start_ns) {
		note_error(ctx, errno ? errno : EIO, "clock_gettime(start)");
		return;
	}
	if (event->op == 'W') {
		bytes = retry_pwrite(ctx->device_fd, expected,
				     SWAPZ_REPLAY_PAGE_BYTES, offset);
	} else {
		bytes = retry_pread(ctx->device_fd, worker->read_page,
				    SWAPZ_REPLAY_PAGE_BYTES, offset);
	}
	end_ns = monotonic_ns();
	if (bytes != (ssize_t)SWAPZ_REPLAY_PAGE_BYTES) {
		note_error(ctx, bytes < 0 ? errno : EIO,
			   event->op == 'W' ? "short WRITE" : "short READ");
		return;
	}
	if (event->op == 'R' &&
	    memcmp(worker->read_page, expected, SWAPZ_REPLAY_PAGE_BYTES) != 0) {
		note_error(ctx, EIO, "READ payload mismatch");
		return;
	}
	if (!end_ns || end_ns < start_ns) {
		note_error(ctx, EIO, "invalid elapsed clock");
		return;
	}
	if (measured) {
		size_t measured_index = index - ctx->warmup_ops;

		ctx->latencies[measured_index].op = event->op;
		ctx->latencies[measured_index].ns = end_ns - start_ns;
	}
}

static void replay_waves(struct replay_worker *worker, size_t first, size_t count,
			 bool measured)
{
	struct replay_context *ctx = worker->ctx;
	size_t end = first + count;
	size_t index;

	for (index = first + worker->lane; index < end; index += ctx->qd) {
		replay_one(worker, index, measured);
		pthread_barrier_wait(&ctx->wave_barrier);
	}
}

static void replay_persistent(struct replay_worker *worker, size_t first,
			      size_t count, bool measured)
{
	struct replay_context *ctx = worker->ctx;
	size_t end = first + count;
	size_t index;

	for (index = first + worker->lane; index < end; index += ctx->qd)
		replay_one(worker, index, measured);
}

static void *worker_main(void *opaque)
{
	struct replay_worker *worker = opaque;
	struct replay_context *ctx = worker->ctx;

	if (ctx->mode == REPLAY_WAVES)
		replay_waves(worker, 0, ctx->warmup_ops, false);
	else
		replay_persistent(worker, 0, ctx->warmup_ops, false);

	pthread_barrier_wait(&ctx->ready_barrier);
	pthread_barrier_wait(&ctx->start_barrier);

	if (ctx->mode == REPLAY_WAVES)
		replay_waves(worker, ctx->warmup_ops, ctx->measure_ops, true);
	else
		replay_persistent(worker, ctx->warmup_ops, ctx->measure_ops, true);

	pthread_barrier_wait(&ctx->done_barrier);
	return NULL;
}

static bool parse_u64(const char *text, uint64_t *value)
{
	char *end = NULL;
	unsigned long long parsed;

	errno = 0;
	parsed = strtoull(text, &end, 10);
	if (errno || !text[0] || !end || *end)
		return false;
	*value = (uint64_t)parsed;
	return true;
}

/* The Python parent validated the canonical JSONL trace and its hashes.
 * Use a fixed binary, regular-file FD only to avoid re-parsing ASCII in C.
 * All records are validated again before starting worker threads.
 */
static int read_plan_bytes(int plan_fd, void *destination, size_t bytes,
			   off_t offset)
{
	uint8_t *next = destination;

	while (bytes) {
		const size_t chunk = bytes > 1048576U ? 1048576U : bytes;
		ssize_t received = pread(plan_fd, next, chunk, offset);

		if (received < 0 && errno == EINTR)
			continue;
		if (received <= 0)
			return received == 0 ? EINVAL : errno;
		next += (size_t)received;
		bytes -= (size_t)received;
		offset += (off_t)received;
	}
	return 0;
}

static int load_plan(int plan_fd, struct replay_context *ctx)
{
	struct stat plan_stat;
	uint8_t header[SWAPZ_REPLAY_PLAN_HEADER_BYTES];
	uint64_t event_count;
	size_t expected_bytes;
	size_t index;
	int error;

	if (ctx->event_count >
	    (SIZE_MAX - SWAPZ_REPLAY_PLAN_HEADER_BYTES) /
	    sizeof(*ctx->events))
		return EOVERFLOW;
	expected_bytes = SWAPZ_REPLAY_PLAN_HEADER_BYTES +
		ctx->event_count * sizeof(*ctx->events);
	if (fstat(plan_fd, &plan_stat) != 0)
		return errno;
	if (!S_ISREG(plan_stat.st_mode) || plan_stat.st_size < 0 ||
	    (uint64_t)plan_stat.st_size != (uint64_t)expected_bytes)
		return EINVAL;
	error = read_plan_bytes(plan_fd, header, sizeof(header), 0);
	if (error)
		return error;
	if (memcmp(header, "SWZPLAN", 8) != 0)
		return EINVAL;
	memcpy(&event_count, header + 8, sizeof(event_count));
	if (event_count != ctx->event_count)
		return EINVAL;
	error = read_plan_bytes(plan_fd, ctx->events,
				ctx->event_count * sizeof(*ctx->events),
				(off_t)sizeof(header));
	if (error)
		return error;
	for (index = 0; index < ctx->event_count; ++index) {
		const struct replay_event *event = &ctx->events[index];

		if ((event->op != 'R' && event->op != 'W') ||
		    event->reserved != 0 ||
		    event->phase != (index < ctx->warmup_ops ? 0U : 1U) ||
		    event->lane >= ctx->qd ||
		    event->lane != (uint8_t)(index % ctx->qd) ||
		    event->fixture >= ctx->fixture_pages)
			return EINVAL;
	}
	return 0;
}

static int write_results(const struct replay_context *ctx)
{
	struct stat result_stat;
	const uint8_t *next = (const uint8_t *)ctx->latencies;
	size_t bytes;
	size_t index;
	off_t offset = 0;

	if (ctx->measure_ops > SIZE_MAX / sizeof(*ctx->latencies))
		return EOVERFLOW;
	bytes = ctx->measure_ops * sizeof(*ctx->latencies);
	if (fstat(ctx->result_fd, &result_stat) != 0)
		return errno;
	/* Python created this private, initially empty regular result file. */
	if (!S_ISREG(result_stat.st_mode) || result_stat.st_size != 0)
		return EINVAL;
	for (index = 0; index < ctx->measure_ops; ++index) {
		const struct replay_latency *latency = &ctx->latencies[index];
		static const uint8_t zero_padding[7];

		if ((latency->op != 'R' && latency->op != 'W') ||
		    !latency->ns ||
		    memcmp(latency->reserved, zero_padding,
			   sizeof(zero_padding)) != 0)
			return EINVAL;
	}
	/* Serialization occurs after the measured DONE boundary. One bounded
	 * contiguous write path replaces per-operation fprintf formatting.
	 */
	while (bytes) {
		const size_t chunk = bytes > 1048576U ? 1048576U : bytes;
		ssize_t written = pwrite(ctx->result_fd, next, chunk, offset);

		if (written < 0 && errno == EINTR)
			continue;
		if (written <= 0)
			return written == 0 ? EIO : errno;
		next += (size_t)written;
		bytes -= (size_t)written;
		offset += (off_t)written;
	}
	return 0;
}

/*
 * Optional, untimed prefill. The Python owner has independently authenticated
 * the trace, fixture, opened target and requested mapping before inheritance.
 * Keep the exact single-page pwrite/fsync/pread + byte oracle ordering; this
 * mode never starts measured workers or returns success on a short I/O.
 */
static int run_native_prefill(int argc, char **argv)
{
	struct stat fixture_stat, device_stat;
	uint64_t values[5];
	uint64_t logical_pages, stride, offset, fixture_pages;
	const uint8_t *fixture = MAP_FAILED;
	uint8_t *read_page = NULL;
	const char *failure = "arguments";
	const char *private_fixture = getenv("SWAPZ_PRIVATE_FIXTURE");
	size_t index;
	int device_fd, fixture_fd;
	int error = 0;

	if (argc != 7 || strcmp(argv[1], "prefill") != 0)
		return 2;
	for (index = 2; index < 7; ++index) {
		if (!parse_u64(argv[index], &values[index - 2])) {
			error = EINVAL;
			goto out;
		}
	}
	if (values[0] > INT32_MAX || values[1] > INT32_MAX ||
	    !values[2] || values[2] > INT64_MAX / SWAPZ_REPLAY_PAGE_BYTES ||
	    !values[3] || values[4] >= values[3] ||
	    (values[2] - 1) > (UINT64_MAX - values[4]) / values[3]) {
		error = EINVAL;
		goto out;
	}
	device_fd = (int)values[0];
	fixture_fd = (int)values[1];
	logical_pages = values[2];
	stride = values[3];
	offset = values[4];

	failure = "parent death protection";
	if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0 || getppid() == 1) {
		error = errno ? errno : EPROTO;
		goto out;
	}
	if (private_fixture && strcmp(private_fixture, "1") == 0) {
		const struct rlimit zero_core = { .rlim_cur = 0, .rlim_max = 0 };

		failure = "private memory protection";
		if (setrlimit(RLIMIT_CORE, &zero_core) != 0 ||
		    prctl(PR_SET_DUMPABLE, 0, 0L, 0L, 0L) != 0 ||
		    mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
			error = errno;
			goto out;
		}
	}
	failure = "opened descriptor admission";
	if (fstat(fixture_fd, &fixture_stat) != 0 ||
	    fstat(device_fd, &device_stat) != 0) {
		error = errno;
		goto out;
	}
	if (!S_ISREG(fixture_stat.st_mode) || fixture_stat.st_size <= 0 ||
	    fixture_stat.st_size % SWAPZ_REPLAY_PAGE_BYTES ||
	    (!S_ISBLK(device_stat.st_mode) && !S_ISREG(device_stat.st_mode)) ||
	    (S_ISREG(device_stat.st_mode) &&
	     ((device_stat.st_dev == fixture_stat.st_dev &&
	       device_stat.st_ino == fixture_stat.st_ino) ||
	      device_stat.st_size < 0 ||
	      (uint64_t)device_stat.st_size <
		      logical_pages * SWAPZ_REPLAY_PAGE_BYTES))) {
		error = EINVAL;
		goto out;
	}
	fixture_pages = (uint64_t)fixture_stat.st_size / SWAPZ_REPLAY_PAGE_BYTES;
	fixture = mmap(NULL, (size_t)fixture_stat.st_size, PROT_READ,
		       MAP_PRIVATE, fixture_fd, 0);
	if (fixture == MAP_FAILED) {
		error = errno;
		goto out;
	}
	failure = "prefill buffer allocation";
	error = posix_memalign((void **)&read_page, SWAPZ_REPLAY_PAGE_BYTES,
			       SWAPZ_REPLAY_PAGE_BYTES);
	if (error)
		goto out;

	for (uint64_t page = 0; page < logical_pages; ++page) {
		const uint64_t fixture_index = (page * stride + offset) % fixture_pages;
		const uint8_t *expected = fixture +
			(size_t)fixture_index * SWAPZ_REPLAY_PAGE_BYTES;
		const off_t page_offset = (off_t)(page * SWAPZ_REPLAY_PAGE_BYTES);
		ssize_t bytes;

		failure = "short prefill WRITE";
		bytes = retry_pwrite(device_fd, expected, SWAPZ_REPLAY_PAGE_BYTES,
				     page_offset);
		if (bytes != SWAPZ_REPLAY_PAGE_BYTES) {
			error = bytes < 0 ? errno : EIO;
			goto out;
		}
	}
	failure = "prefill fsync";
	if (fsync(device_fd) != 0) {
		error = errno;
		goto out;
	}
	for (uint64_t page = 0; page < logical_pages; ++page) {
		const uint64_t fixture_index = (page * stride + offset) % fixture_pages;
		const uint8_t *expected = fixture +
			(size_t)fixture_index * SWAPZ_REPLAY_PAGE_BYTES;
		const off_t page_offset = (off_t)(page * SWAPZ_REPLAY_PAGE_BYTES);
		ssize_t bytes;

		failure = "short prefill READ";
		bytes = retry_pread(device_fd, read_page, SWAPZ_REPLAY_PAGE_BYTES,
				    page_offset);
		if (bytes != SWAPZ_REPLAY_PAGE_BYTES) {
			error = bytes < 0 ? errno : EIO;
			goto out;
		}
		failure = "prefill byte oracle";
		if (memcmp(read_page, expected, SWAPZ_REPLAY_PAGE_BYTES) != 0) {
			error = EIO;
			goto out;
		}
	}
out:
	free(read_page);
	if (fixture != MAP_FAILED)
		munmap((void *)fixture, (size_t)fixture_stat.st_size);
	if (error) {
		dprintf(STDERR_FILENO, "io-replay-native: %s: %s\n",
			failure, strerror(error));
		return 2;
	}
	puts("PREFILL_VERIFIED");
	return 0;
}

int main(int argc, char **argv)
{
	struct replay_context ctx = {0};
	struct replay_worker workers[SWAPZ_REPLAY_MAX_QD] = {0};
	pthread_t threads[SWAPZ_REPLAY_MAX_QD] = {0};
	struct stat fixture_stat;
	struct rusage cpu_before = {0}, cpu_after = {0};
	uint64_t values[7];
	uint64_t wall_start_ns = 0, wall_end_ns = 0;
	uint64_t user_us, system_us;
	size_t started = 0;
	unsigned int index;
	char go[16];
	int error = 0;
	int fixture_fd, plan_fd;
	const char *private_fixture = getenv("SWAPZ_PRIVATE_FIXTURE");

	setvbuf(stdout, NULL, _IOLBF, 0);
	if (argc == 7 && strcmp(argv[1], "prefill") == 0)
		return run_native_prefill(argc, argv);
	if (argc != 9) {
		fprintf(stderr,
			"usage: %s DEVICE_FD FIXTURE_FD PLAN_FD RESULT_FD QD "
			"WARMUP_OPS MEASURE_OPS waves|persistent\n",
			argv[0]);
		return 2;
	}
	for (index = 1; index <= 7; ++index) {
		if (!parse_u64(argv[index], &values[index - 1]) ||
		    values[index - 1] > INT32_MAX) {
			fprintf(stderr, "io-replay-native: invalid numeric argument\n");
			return 2;
		}
	}
	ctx.device_fd = (int)values[0];
	fixture_fd = (int)values[1];
	plan_fd = (int)values[2];
	ctx.result_fd = (int)values[3];
	ctx.qd = (unsigned int)values[4];
	ctx.warmup_ops = (size_t)values[5];
	ctx.measure_ops = (size_t)values[6];
	ctx.event_count = ctx.warmup_ops + ctx.measure_ops;
	if (!ctx.qd || ctx.qd > SWAPZ_REPLAY_MAX_QD || !ctx.measure_ops ||
	    ctx.warmup_ops % ctx.qd || ctx.measure_ops % ctx.qd ||
	    ctx.event_count < ctx.measure_ops) {
		fprintf(stderr, "io-replay-native: invalid QD or operation count\n");
		return 2;
	}
	if (strcmp(argv[8], "waves") == 0)
		ctx.mode = REPLAY_WAVES;
	else if (strcmp(argv[8], "persistent") == 0)
		ctx.mode = REPLAY_PERSISTENT;
	else {
		fprintf(stderr, "io-replay-native: invalid replay mode\n");
		return 2;
	}
	if (prctl(PR_SET_PDEATHSIG, SIGTERM) != 0) {
		perror("io-replay-native: PR_SET_PDEATHSIG");
		return 2;
	}
	if (getppid() == 1)
		return 2;
	if (private_fixture && strcmp(private_fixture, "1") == 0) {
		const struct rlimit zero_core = { .rlim_cur = 0, .rlim_max = 0 };

		/* Each exec must protect its own fixture mapping and read buffers. */
		if (setrlimit(RLIMIT_CORE, &zero_core) != 0 ||
		    prctl(PR_SET_DUMPABLE, 0, 0L, 0L, 0L) != 0 ||
		    mlockall(MCL_CURRENT | MCL_FUTURE) != 0) {
			perror("io-replay-native: private memory protection");
			return 2;
		}
	}
	if (fstat(fixture_fd, &fixture_stat) != 0 || fixture_stat.st_size <= 0 ||
	    fixture_stat.st_size % SWAPZ_REPLAY_PAGE_BYTES) {
		fprintf(stderr, "io-replay-native: invalid fixture fd\n");
		return 2;
	}
	ctx.fixture_pages =
		(size_t)fixture_stat.st_size / SWAPZ_REPLAY_PAGE_BYTES;
	ctx.fixture = mmap(NULL, (size_t)fixture_stat.st_size, PROT_READ,
			   MAP_PRIVATE, fixture_fd, 0);
	if (ctx.fixture == MAP_FAILED) {
		perror("io-replay-native: mmap fixture");
		return 2;
	}
	ctx.events = calloc(ctx.event_count, sizeof(*ctx.events));
	ctx.latencies = calloc(ctx.measure_ops, sizeof(*ctx.latencies));
	if (!ctx.events || !ctx.latencies) {
		error = ENOMEM;
		goto out;
	}
	error = load_plan(plan_fd, &ctx);
	if (error)
		goto out;
	atomic_init(&ctx.error_code, 0);
	error = pthread_barrier_init(&ctx.wave_barrier, NULL, ctx.qd);
	if (error)
		goto out;
	error = pthread_barrier_init(&ctx.ready_barrier, NULL, ctx.qd + 1U);
	if (error)
		goto out;
	error = pthread_barrier_init(&ctx.start_barrier, NULL, ctx.qd + 1U);
	if (error)
		goto out;
	error = pthread_barrier_init(&ctx.done_barrier, NULL, ctx.qd + 1U);
	if (error)
		goto out;
	for (index = 0; index < ctx.qd; ++index) {
		workers[index].ctx = &ctx;
		workers[index].lane = index;
		error = posix_memalign((void **)&workers[index].read_page,
				       SWAPZ_REPLAY_PAGE_BYTES,
				       SWAPZ_REPLAY_PAGE_BYTES);
		if (error)
			goto release_threads;
	}
	for (index = 0; index < ctx.qd; ++index) {
		error = pthread_create(&threads[index], NULL, worker_main,
				       &workers[index]);
		if (error) {
			dprintf(STDERR_FILENO,
				"io-replay-native: pthread_create: %s\n",
				strerror(error));
			return 2;
		}
		started++;
	}

	pthread_barrier_wait(&ctx.ready_barrier);
	error = atomic_load(&ctx.error_code);
	if (error) {
		/*
		 * Workers are parked on start_barrier. Exit the process immediately
		 * instead of trying to join a deliberately unreleased measured phase;
		 * process teardown terminates those private test threads.
		 */
		printf("FAIL %d\n", error);
		fflush(stdout);
		return 2;
	}
	printf("READY\n");
	if (!fgets(go, sizeof(go), stdin) || strcmp(go, "GO\n") != 0) {
		note_error(&ctx, EPROTO, "missing GO gate");
		pthread_barrier_wait(&ctx.start_barrier);
		pthread_barrier_wait(&ctx.done_barrier);
		error = EPROTO;
		goto join_threads;
	}
	if (getrusage(RUSAGE_SELF, &cpu_before) != 0)
		note_error(&ctx, errno, "getrusage(start)");
	wall_start_ns = monotonic_ns();
	if (!wall_start_ns)
		note_error(&ctx, errno ? errno : EIO,
			   "clock_gettime(measure start)");
	pthread_barrier_wait(&ctx.start_barrier);
	pthread_barrier_wait(&ctx.done_barrier);
	if (!atomic_load(&ctx.error_code) && fsync(ctx.device_fd) != 0)
		note_error(&ctx, errno, "fsync");
	wall_end_ns = monotonic_ns();
	if (!wall_end_ns || wall_end_ns < wall_start_ns)
		note_error(&ctx, EIO, "clock_gettime(measure end)");
	if (getrusage(RUSAGE_SELF, &cpu_after) != 0)
		note_error(&ctx, errno, "getrusage(end)");
	error = atomic_load(&ctx.error_code);
	if (error) {
		printf("FAIL %d\n", error);
		goto join_threads;
	}
	user_us = timeval_us(&cpu_after.ru_utime) -
		timeval_us(&cpu_before.ru_utime);
	system_us = timeval_us(&cpu_after.ru_stime) -
		timeval_us(&cpu_before.ru_stime);
	printf("DONE %" PRIu64 " %" PRIu64 " %" PRIu64 " %ld\n",
	       wall_end_ns - wall_start_ns, (uint64_t)(user_us * 1000ULL),
	       (uint64_t)(system_us * 1000ULL), cpu_after.ru_maxrss);
	error = write_results(&ctx);

join_threads:
	for (index = 0; index < started; ++index)
		pthread_join(threads[index], NULL);
release_threads:
	for (index = 0; index < ctx.qd; ++index)
		free(workers[index].read_page);
	pthread_barrier_destroy(&ctx.done_barrier);
	pthread_barrier_destroy(&ctx.start_barrier);
	pthread_barrier_destroy(&ctx.ready_barrier);
	pthread_barrier_destroy(&ctx.wave_barrier);
out:
	free(ctx.latencies);
	free(ctx.events);
	if (ctx.fixture && ctx.fixture != MAP_FAILED)
		munmap((void *)ctx.fixture, (size_t)fixture_stat.st_size);
	if (error) {
		errno = error;
		perror("io-replay-native");
		return 2;
	}
	return 0;
}
