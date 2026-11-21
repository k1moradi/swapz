// SPDX-License-Identifier: GPL-2.0-only
/* Host-only original-source LZO1X import profile, never a live authority. */
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <openssl/sha.h>
#include "codec.h"
#include "linux/lzo.h"
#define PAGE_BYTES 4096U
#define CHECK(condition) do { if (!(condition)) { fprintf(stderr, "ROUND056_FIRST_ERROR line=%u %s\n", (unsigned)__LINE__, #condition); return 1; } } while (0)
struct source_record {
 uint32_t compressed_length, crc32c;
 uint8_t sha256[32], codec, version, dictionary;
};
/* No global crypto_acomp selection, borrowed zsmalloc address or pool pointer.
 * Exclusive caller-owned input and separate fixed 4096 scratch/output are
 * required. Failed decode never modifies output or acknowledges any BIO. */
static int decode(const struct source_record *record, const uint8_t *source,
                  uint8_t scratch[PAGE_BYTES], uint8_t output[PAGE_BYTES])
{
 uint8_t hash[32];
 size_t output_length = PAGE_BYTES;
 if (record->codec != 2U || record->version != 1U || record->dictionary != 0U)
  return -EOPNOTSUPP;
 if (!record->compressed_length || record->compressed_length > SWAPZ_MAX_COMPRESSED)
  return -EMSGSIZE;
 if (swapz_crc32c_bytes(source, record->compressed_length) != record->crc32c)
  return -EBADMSG;
 /* True original pinned lib/lzo implementation; it rejects trailing input. */
 if (lzo1x_decompress_safe(source, record->compressed_length, scratch, &output_length) != LZO_E_OK ||
     output_length != PAGE_BYTES)
  return -EBADMSG;
 if (!SHA256(scratch, PAGE_BYTES, hash)) return -EIO;
 if (memcmp(hash, record->sha256, 32U) != 0) return -EBADMSG;
 memcpy(output, scratch, PAGE_BYTES);
 return 0;
}
static int run(void)
{
 uint8_t original[PAGE_BYTES], compressed[PAGE_BYTES + 512U];
 uint8_t scratch[PAGE_BYTES], output[PAGE_BYTES], untouched[PAGE_BYTES];
 uint8_t workspace[LZO1X_1_MEM_COMPRESS];
 unsigned accepted = 0;
 for (unsigned seed=0; seed<32U; ++seed) {
  struct source_record record = { .codec=2U, .version=1U };
  size_t length=sizeof(compressed);
  for(size_t i=0;i<PAGE_BYTES;i++) original[i] = (uint8_t)((i / (32U + seed)) % 5U);
  CHECK(lzo1x_1_compress_safe(original,PAGE_BYTES,compressed,&length,workspace)==LZO_E_OK);
  CHECK(length>0U);
  if(length>SWAPZ_MAX_COMPRESSED) continue; /* full ordinary RAW fallback */
  accepted++;
  record.compressed_length=(uint32_t)length;
  record.crc32c=swapz_crc32c_bytes(compressed,record.compressed_length);
  CHECK(SHA256(original,PAGE_BYTES,record.sha256)!=NULL);
  memset(output,0x7a,sizeof(output));
  CHECK(decode(&record,compressed,scratch,output)==0);
  CHECK(memcmp(output,original,PAGE_BYTES)==0);
  memcpy(untouched,output,PAGE_BYTES);
  compressed[length]=0x5a; record.compressed_length++;
  record.crc32c=swapz_crc32c_bytes(compressed,record.compressed_length);
  CHECK(decode(&record,compressed,scratch,output)==-EBADMSG); /* trailing LZO input */
  CHECK(memcmp(output,untouched,PAGE_BYTES)==0);
  record.compressed_length--; record.crc32c=swapz_crc32c_bytes(compressed,record.compressed_length);
  record.crc32c ^= 1U;
  CHECK(decode(&record,compressed,scratch,output)==-EBADMSG);
  record.crc32c ^= 1U;
  record.sha256[0] ^= 1U;
  CHECK(decode(&record,compressed,scratch,output)==-EBADMSG);
  record.sha256[0] ^= 1U;
  record.version=2U;
  CHECK(decode(&record,compressed,scratch,output)==-EOPNOTSUPP);
  record.version=1U;
  record.dictionary=1U;
  CHECK(decode(&record,compressed,scratch,output)==-EOPNOTSUPP);
  record.dictionary=0U;
  CHECK(memcmp(output,untouched,PAGE_BYTES)==0);
 }
 CHECK(accepted>0U);
 printf("ROUND056_PINNED_ORIGINAL_LZO1X_HOST_PASS accepted=%u pool_independent=1 auth=0\n",accepted);
 return 0;
}
int main(void) { return run(); }
