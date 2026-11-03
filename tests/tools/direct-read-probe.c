#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

enum {
    PROBE_BYTES = 4096,
    PROBE_ALIGN = 4096,
};

int main(int argc, char **argv)
{
    void *buffer = NULL;
    ssize_t read_ret = -2;
    int read_errno = 0;
    int close_ret = -2;
    int close_errno = 0;
    int fd;
    int alloc_error;

    if (argc != 2) {
        fprintf(stderr, "DIRECT_READ_PROBE usage_error=1\n");
        return 64;
    }

    alloc_error = posix_memalign(&buffer, PROBE_ALIGN, PROBE_BYTES);
    if (alloc_error) {
        fprintf(stderr, "DIRECT_READ_PROBE alloc_error=%d\n", alloc_error);
        return 65;
    }

    errno = 0;
    fd = open(argv[1], O_RDONLY | O_DIRECT | O_CLOEXEC);
    if (fd < 0) {
        int open_errno = errno;

        printf("DIRECT_READ_PROBE open_ret=-1 open_errno=%d "
               "read_ret=-2 read_errno=0 close_ret=-2 close_errno=0\n",
               open_errno);
        free(buffer);
        return 66;
    }

    errno = 0;
    read_ret = pread(fd, buffer, PROBE_BYTES, 0);
    if (read_ret < 0)
        read_errno = errno;

    errno = 0;
    close_ret = close(fd);
    if (close_ret < 0)
        close_errno = errno;

    printf("DIRECT_READ_PROBE open_ret=0 open_errno=0 "
           "read_ret=%zd read_errno=%d close_ret=%d close_errno=%d\n",
           read_ret, read_errno, close_ret, close_errno);
    free(buffer);

    if (read_ret == -1 && read_errno == EIO)
        return 0;
    if (read_ret == PROBE_BYTES)
        return 10;
    if (read_ret >= 0)
        return 11;
    return 12;
}
