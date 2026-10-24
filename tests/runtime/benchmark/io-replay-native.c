#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <signal.h>
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

struct replay_event {
	uint32_t page;
	uint32_t fixture;
	uint8_t lane;
	uint8_t phase;
	char op;
};

struct replay_latency {
	char op;
	uint64_t ns;
};

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

static int load_plan(int plan_fd, struct replay_context *ctx)
{
	FILE *stream = NULL;
	char *line = NULL;
	size_t capacity = 0;
	size_t index = 0;
	int duplicate_fd;
	int error = 0;

	duplicate_fd = dup(plan_fd);
	if (duplicate_fd < 0)
		return errno;
	stream = fdopen(duplicate_fd, "r");
	if (!stream) {
		error = errno;
		close(duplicate_fd);
		return error;
	}
	while (getline(&line, &capacity, stream) >= 0) {
		struct replay_event *event;
		unsigned int page, fixture, phase, lane;
		char op, extra;
		int fields;

		if (index >= ctx->event_count) {
			error = EOVERFLOW;
			break;
		}
		fields = sscanf(line, " %c %u %u %u %u %c",
				&op, &page, &fixture, &phase, &lane, &extra);
		if (fields != 5 || (op != 'R' && op != 'W') ||
		    phase > 1U || lane >= ctx->qd ||
		    lane != index % ctx->qd ||
		    phase != (index < ctx->warmup_ops ? 0U : 1U) ||
		    fixture >= ctx->fixture_pages) {
			error = EINVAL;
			break;
		}
		event = &ctx->events[index++];
		event->op = op;
		event->page = page;
		event->fixture = fixture;
		event->phase = (uint8_t)phase;
		event->lane = (uint8_t)lane;
	}
	if (!error && ferror(stream))
		error = errno ? errno : EIO;
	if (!error && index != ctx->event_count)
		error = EINVAL;
	free(line);
	fclose(stream);
	return error;
}

static int write_results(const struct replay_context *ctx)
{
	FILE *stream;
	int duplicate_fd;
	size_t index;

	duplicate_fd = dup(ctx->result_fd);
	if (duplicate_fd < 0)
		return errno;
	stream = fdopen(duplicate_fd, "w");
	if (!stream) {
		int error = errno;

		close(duplicate_fd);
		return error;
	}
	for (index = 0; index < ctx->measure_ops; ++index) {
		const struct replay_latency *latency = &ctx->latencies[index];

		if ((latency->op != 'R' && latency->op != 'W') || !latency->ns) {
			fclose(stream);
			return EINVAL;
		}
		if (fprintf(stream, "%c %" PRIu64 "\n", latency->op,
			    latency->ns) < 0) {
			int error = errno ? errno : EIO;

			fclose(stream);
			return error;
		}
	}
	if (fflush(stream) != 0) {
		int error = errno;

		fclose(stream);
		return error;
	}
	if (fclose(stream) != 0)
		return errno;
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

	setvbuf(stdout, NULL, _IOLBF, 0);
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
