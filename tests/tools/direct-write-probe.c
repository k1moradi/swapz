#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

enum {
    PROBE_BYTES = 4096,
    PROBE_ALIGN = 4096,
};

static void fill_nonzero_pattern(uint8_t *buffer)
{
    uint32_t state = 0x6d2b79f5U;
    size_t i;

    for (i = 0; i < PROBE_BYTES; ++i) {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        buffer[i] = (uint8_t)(state | 1U);
    }
}

int main(int argc, char **argv)
{
    void *buffer = NULL;
    ssize_t write_ret = -2;
    int write_errno = 0;
    int close_ret = -2;
    int close_errno = 0;
    int fd;
    int alloc_error;

    if (argc != 2) {
        fprintf(stderr, "DIRECT_WRITE_PROBE usage_error=1\n");
        return 64;
    }

    alloc_error = posix_memalign(&buffer, PROBE_ALIGN, PROBE_BYTES);
    if (alloc_error) {
        fprintf(stderr, "DIRECT_WRITE_PROBE alloc_error=%d\n", alloc_error);
        return 65;
    }
    fill_nonzero_pattern(buffer);

    errno = 0;
    fd = open(argv[1], O_WRONLY | O_DIRECT | O_CLOEXEC);
    if (fd < 0) {
        int open_errno = errno;

        printf("DIRECT_WRITE_PROBE open_ret=-1 open_errno=%d "
               "write_ret=-2 write_errno=0 close_ret=-2 close_errno=0\n",
               open_errno);
        free(buffer);
        return 66;
    }

    errno = 0;
    write_ret = pwrite(fd, buffer, PROBE_BYTES, 0);
    if (write_ret < 0)
        write_errno = errno;

    errno = 0;
    close_ret = close(fd);
    if (close_ret < 0)
        close_errno = errno;

    printf("DIRECT_WRITE_PROBE open_ret=0 open_errno=0 "
           "write_ret=%zd write_errno=%d close_ret=%d close_errno=%d\n",
           write_ret, write_errno, close_ret, close_errno);
    free(buffer);

    if (write_ret == -1 && write_errno == EIO)
        return 0;
    if (write_ret == PROBE_BYTES)
        return 10;
    if (write_ret >= 0)
        return 11;
    return 12;
}
