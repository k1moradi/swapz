#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define PAGE 4096U
#define MAX_QD 64U
struct result { int done; int error; };
struct ctx {
    int fd;
    const unsigned char *page;
    unsigned pages;
    unsigned qd;
    unsigned extra_writes;
    int expect_enospc;
    atomic_uint next;
    atomic_uint successes;
    atomic_uint failures;
    atomic_int stop;
    atomic_int first_error;
    atomic_uint first_page;
    struct result *results;
};
struct worker { struct ctx *ctx; };

static void *write_worker(void *arg)
{
    struct ctx *c = ((struct worker *)arg)->ctx;
    while (!atomic_load(&c->stop)) {
        unsigned page = atomic_fetch_add(&c->next, 1);
        ssize_t n;
        int error;
        if (page >= c->pages) break;
        n = pwrite(c->fd, c->page, PAGE, (off_t)page * PAGE);
        error = n == (ssize_t)PAGE ? 0 : (n < 0 ? errno : EIO);
        c->results[page].done = error == 0;
        c->results[page].error = error;
        if (!error) {
            atomic_fetch_add(&c->successes, 1);
        } else {
            int expected = 0;
            atomic_fetch_add(&c->failures, 1);
            atomic_store(&c->stop, 1);
            if (atomic_compare_exchange_strong(&c->first_error, &expected, error))
                atomic_store(&c->first_page, page);
            break;
        }
    }
    return NULL;
}

int main(int argc, char **argv)
{
    const char *dev = NULL, *fixture = NULL, *results_path = NULL;
    unsigned pages = 8192, qd = 32, extra_writes = 0;
    int expect_enospc = 0;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--device") && ++i < argc) dev = argv[i];
        else if (!strcmp(argv[i], "--fixture") && ++i < argc) fixture = argv[i];
        else if (!strcmp(argv[i], "--pages") && ++i < argc) pages = strtoul(argv[i], NULL, 10);
        else if (!strcmp(argv[i], "--qd") && ++i < argc) qd = strtoul(argv[i], NULL, 10);
        else if (!strcmp(argv[i], "--extra-writes") && ++i < argc) extra_writes = strtoul(argv[i], NULL, 10);
        else if (!strcmp(argv[i], "--results") && ++i < argc) results_path = argv[i];
        else if (!strcmp(argv[i], "--expect-enospc")) expect_enospc = 1;
        else { fprintf(stderr, "usage: %s --device DEV --fixture PAGE.bin [--pages N --qd N --results CSV --expect-enospc]\n", argv[0]); return 2; }
    }
    if (!dev || !fixture || !pages || qd < 1 || qd > MAX_QD || extra_writes > 64) return 2;
    int f = open(fixture, O_RDONLY | O_CLOEXEC);
    if (f < 0) { perror("open fixture"); return 2; }
    void *page = NULL;
    if (posix_memalign(&page, PAGE, PAGE)) { close(f); return 2; }
    if (pread(f, page, PAGE, 0) != PAGE) { perror("read fixture"); close(f); free(page); return 2; }
    close(f);
    int fd = open(dev, O_RDWR | O_DIRECT | O_CLOEXEC);
    if (fd < 0) { perror("open target"); free(page); return 2; }
    struct ctx c = {.fd=fd,.page=page,.pages=pages,.qd=qd,.extra_writes=extra_writes,.expect_enospc=expect_enospc};
    c.results = calloc(pages, sizeof(*c.results));
    pthread_t *threads = calloc(qd, sizeof(*threads));
    struct worker *workers = calloc(qd, sizeof(*workers));
    if (!c.results || !threads || !workers) { close(fd); free(page); free(c.results); free(threads); free(workers); return 2; }
    atomic_init(&c.next, 0); atomic_init(&c.successes, 0); atomic_init(&c.failures, 0);
    atomic_init(&c.stop, 0);
    atomic_init(&c.first_error, 0); atomic_init(&c.first_page, UINT32_MAX);
    for (unsigned i = 0; i < qd; ++i) {
        workers[i].ctx = &c;
        if (pthread_create(&threads[i], NULL, write_worker, &workers[i])) { perror("pthread_create"); return 2; }
    }
    for (unsigned i = 0; i < qd; ++i) pthread_join(threads[i], NULL);
    /* Separate overwrite phase: with all logical slots populated, the first
     * replacement forces foreground allocation/GC at the full-destination
     * boundary instead of mistaking initial fill for a reclaim test. */
    if (!atomic_load(&c.stop)) {
        for (unsigned i = 0; i < extra_writes; ++i) {
            unsigned logical_page = i % pages;
            ssize_t n = pwrite(fd, page, PAGE, (off_t)logical_page * PAGE);
            int error = n == (ssize_t)PAGE ? 0 : (n < 0 ? errno : EIO);
            if (error) {
                int expected = 0;
                atomic_fetch_add(&c.failures, 1);
                atomic_store(&c.stop, 1);
                if (atomic_compare_exchange_strong(&c.first_error, &expected, error))
                    atomic_store(&c.first_page, logical_page);
                break;
            }
            atomic_fetch_add(&c.successes, 1);
        }
    }
    unsigned successes = atomic_load(&c.successes), failures = atomic_load(&c.failures);
    int first_error = atomic_load(&c.first_error);
    unsigned first_page = atomic_load(&c.first_page);
    if (results_path) {
        FILE *out = fopen(results_path, "w");
        if (!out) { perror("fopen results"); return 2; }
        fputs("logical_page,completed,errno\n", out);
        for (unsigned i = 0; i < pages; ++i)
            if (c.results[i].done || c.results[i].error)
                fprintf(out, "%u,%d,%d\n", i, c.results[i].done, c.results[i].error);
        fclose(out);
    }
    printf("{\"pages_requested\":%u,\"extra_writes_requested\":%u,\"qd\":%u,\"successful_writes\":%u,\"failed_writes\":%u,\"first_failed_page\":%u,\"first_errno\":%d,\"reads_after_failure\":0,\"result\":\"%s\"}\n",
           pages, extra_writes, qd, successes, failures, first_page, first_error,
           expect_enospc && first_error == ENOSPC ? "EXPECTED_ENOSPC" : first_error ? "UNEXPECTED_ERROR" : "UNEXPECTED_SUCCESS");
    close(fd); free(page); free(c.results); free(threads); free(workers);
    if (expect_enospc)
        return first_error == ENOSPC ? 0 : 1;
    return first_error == 0 ? 0 : 1;
}
