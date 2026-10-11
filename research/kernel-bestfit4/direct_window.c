// SPDX-License-Identifier: GPL-2.0-only
/* One aligned 64 KiB direct-write/readback window for the mixed-payload test. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define WINDOW_BYTES (16U * 4096U)
#define ALIGNMENT 4096U

static int read_all(int fd, unsigned char *buffer, size_t length)
{
    size_t done = 0;
    while (done < length) {
        ssize_t count = read(fd, buffer + done, length - done);
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            return -1;
        done += (size_t)count;
    }
    return 0;
}

static int write_all(int fd, const unsigned char *buffer, size_t length)
{
    size_t done = 0;
    while (done < length) {
        ssize_t count = write(fd, buffer + done, length - done);
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            return -1;
        done += (size_t)count;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int input_fd = -1, target_fd = -1, output_fd = -1;
    unsigned char *input = NULL, *readback = NULL;
    struct stat target_stat;
    ssize_t count;
    int rc = 1;

    if (argc != 4) {
        fprintf(stderr, "usage: %s <65536-byte-pages.bin> </dev/mapper/owned-target> <readback.bin>\n", argv[0]);
        return 2;
    }
    input_fd = open(argv[1], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (input_fd < 0) {
        perror("open input");
        goto out;
    }
    if (posix_memalign((void **)&input, ALIGNMENT, WINDOW_BYTES) ||
        posix_memalign((void **)&readback, ALIGNMENT, WINDOW_BYTES)) {
        fprintf(stderr, "aligned allocation failed\n");
        goto out;
    }
    if (read_all(input_fd, input, WINDOW_BYTES)) {
        fprintf(stderr, "input must contain exactly one complete 64 KiB window\n");
        goto out;
    }
    {
        unsigned char extra;
        if (read(input_fd, &extra, 1) != 0) {
            fprintf(stderr, "input contains trailing data\n");
            goto out;
        }
    }
    target_fd = open(argv[2], O_RDWR | O_DIRECT | O_CLOEXEC | O_NOFOLLOW);
    if (target_fd < 0) {
        perror("open owned DM target");
        goto out;
    }
    if (fstat(target_fd, &target_stat) || !S_ISBLK(target_stat.st_mode)) {
        fprintf(stderr, "selected target is not a block device\n");
        goto out;
    }
    count = pwrite(target_fd, input, WINDOW_BYTES, 0);
    if (count != WINDOW_BYTES) {
        if (count < 0)
            perror("single aligned 64 KiB pwrite");
        else
            fprintf(stderr, "single pwrite was short: %zd bytes\n", count);
        goto out;
    }
    if (fsync(target_fd)) {
        perror("fsync owned DM target");
        goto out;
    }
    count = pread(target_fd, readback, WINDOW_BYTES, 0);
    if (count != WINDOW_BYTES) {
        if (count < 0)
            perror("single aligned 64 KiB pread");
        else
            fprintf(stderr, "single pread was short: %zd bytes\n", count);
        goto out;
    }
    if (memcmp(input, readback, WINDOW_BYTES)) {
        fprintf(stderr, "64 KiB readback differs from generated fixture\n");
        goto out;
    }
    output_fd = open(argv[3], O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (output_fd < 0) {
        perror("create readback evidence");
        goto out;
    }
    if (write_all(output_fd, readback, WINDOW_BYTES) || fsync(output_fd)) {
        perror("write readback evidence");
        goto out;
    }
    printf("ONE_ALIGNED_WRITE_BYTES=%u\nONE_ALIGNED_READ_BYTES=%u\nFSYNC=PASS\nREADBACK=BYTE_EXACT\n",
           WINDOW_BYTES, WINDOW_BYTES);
    rc = 0;
out:
    if (output_fd >= 0 && close(output_fd) && rc == 0) {
        perror("close readback evidence");
        rc = 1;
    }
    if (target_fd >= 0 && close(target_fd) && rc == 0) {
        perror("close owned DM target");
        rc = 1;
    }
    if (input_fd >= 0)
        close(input_fd);
    free(input);
    free(readback);
    return rc;
}
