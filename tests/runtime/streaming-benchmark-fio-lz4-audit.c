// SPDX-License-Identifier: GPL-2.0-only
/* Read a regular-file fio capture in 4 KiB pages; emit exact raw LZ4 lengths. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <lz4.h>

#define SWAPZ_PAGE_BYTES 4096
#define SWAPZ_MAX_COMPRESSED_BYTES (4096 - 8 - 8 - 512)

int main(int argc, char **argv)
{
    FILE *in;
    unsigned char page[SWAPZ_PAGE_BYTES];
    char compressed[SWAPZ_MAX_COMPRESSED_BYTES];
    size_t index = 0;
    int length;

    if (argc != 2) {
        fprintf(stderr, "usage: %s <disposable-fio-regular-file>\n", argv[0]);
        return 2;
    }
    in = fopen(argv[1], "rb");
    if (!in) {
        perror("fopen");
        return 2;
    }
    puts("page_index\tpayload_bytes\tkind");
    while (1) {
        size_t n = fread(page, 1, sizeof(page), in);
        if (!n)
            break;
        if (n != sizeof(page)) {
            fprintf(stderr, "truncated 4 KiB page in capture\n");
            fclose(in);
            return 3;
        }
        length = LZ4_compress_fast((const char *)page, compressed,
                                   SWAPZ_PAGE_BYTES,
                                   SWAPZ_MAX_COMPRESSED_BYTES, 1);
        if (length <= 0)
            printf("%zu\t0\traw\n", index);
        else
            printf("%zu\t%d\tcompressed\n", index, length);
        ++index;
    }
    if (ferror(in) || !index) {
        fprintf(stderr, "capture read failed or contains no pages\n");
        fclose(in);
        return 3;
    }
    if (fclose(in)) {
        perror("fclose");
        return 3;
    }
    return 0;
}
