#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "zswap-import-codec.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

/* CRC32C is linked from the original production src/kernel/codec.c. */
static swapz_u32 crc32_ieee(const void *source, unsigned length)
{
    const unsigned char *data = source;
    swapz_u32 state = ~0U;
    for (unsigned index = 0; index < length; ++index) {
        state ^= data[index];
        for (unsigned bit = 0; bit < 8; ++bit)
            state = (state >> 1) ^ ((state & 1U) ? 0xedb88320U : 0U);
    }
    return ~state;
}
static swapz_u8 original[4096], compressed[4096], scratch[4096], out[4096];
static struct swapz_zswap_import_record record;
static struct swapz_zswap_import_read_authority authority;
static int decode(void) {
    return swapz_zswap_import_decode(&record, &authority, compressed,
                record.compressed_length, scratch, sizeof(scratch),
                out, sizeof(out), original);
}
static void reset_output(void) { memset(out, 0xa5, sizeof(out)); }
static void denied(int result) {
    assert(result < 0);
    for (unsigned i=0;i<4096;++i) assert(out[i]==0xa5);
}
int main(void) {
    for (unsigned i=0;i<4096;++i) original[i]=(swapz_u8)(i / 64U);
    int length = LZ4_compress_default((const char *)original,
                                      (char *)compressed, 4096, sizeof(compressed));
    assert(length > 0 && length <= 3568);
    record=(struct swapz_zswap_import_record){
        .logical_page=17,.generation=19,.stored_entry_identity=23,
        .store_generation=29,.gc_epoch=31,.compressed_length=(swapz_u32)length,
        .decoded_length=4096,.compressed_crc32c=swapz_crc32c_bytes(compressed,(swapz_u32)length),
        .representation=SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
        .codec=SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,.version=SWAPZ_ZSWAP_IMPORT_VERSION,
        .stored_eviction=1,.immutable_owned_copy=1,
    };
    assert(SHA256(original,4096,record.original_sha256));
    authority=(struct swapz_zswap_import_read_authority){
        .logical_page=17,.generation=19,.stored_entry_identity=23,
        .store_generation=29,.gc_epoch=31,.actual_lower_read_bytes=(swapz_u32)length,
        .mapping_published_after_durable_write=1,.foreground_write_committed_once=1,
        .upper_write_ack_count=1,.current_owned_ram_session=1
    };
    assert(SWAPZ_ZSWAP_IMPORT_ACTIVE==0);
    reset_output(); assert(decode()==0); assert(!memcmp(out,original,4096));
#define BAD_FIELD(obj,field,wrong) do { __typeof__((obj).field) saved=(obj).field; \
    (obj).field=(wrong);reset_output();denied(decode());(obj).field=saved;} while(0)
    BAD_FIELD(record,representation,0);
    BAD_FIELD(record,codec,2);
    BAD_FIELD(record,version,2);
    BAD_FIELD(record,dictionary_id,1);
    BAD_FIELD(record,stored_eviction,0);
    BAD_FIELD(record,immutable_owned_copy,0);
    BAD_FIELD(record,compressed_length,0);
    BAD_FIELD(record,compressed_length,3569);
    BAD_FIELD(record,decoded_length,4088);
    BAD_FIELD(record,logical_page,18);
    BAD_FIELD(record,generation,18);
    BAD_FIELD(record,store_generation,30);
    BAD_FIELD(record,stored_entry_identity,24);
    BAD_FIELD(record,gc_epoch,32);
    BAD_FIELD(record,compressed_crc32c,record.compressed_crc32c ^ 1U);
    BAD_FIELD(record,compressed_crc32c,crc32_ieee(compressed,(unsigned)length));
    BAD_FIELD(authority,logical_page,18);
    BAD_FIELD(authority,generation,18);
    BAD_FIELD(authority,store_generation,30);
    BAD_FIELD(authority,stored_entry_identity,24);
    BAD_FIELD(authority,gc_epoch,32);
    BAD_FIELD(authority,actual_lower_read_bytes,(swapz_u32)(length-1));
    BAD_FIELD(authority,lower_read_error,-EIO);
    BAD_FIELD(authority,mapping_published_after_durable_write,0);
    BAD_FIELD(authority,foreground_write_committed_once,0);
    BAD_FIELD(authority,upper_write_ack_count,0);
    BAD_FIELD(authority,upper_write_ack_count,2);
    BAD_FIELD(authority,current_owned_ram_session,0);
    BAD_FIELD(authority,teardown_started,1);
    BAD_FIELD(authority,upper_read_ack_count,1);
#undef BAD_FIELD
    record.original_sha256[0]^=1;reset_output();denied(decode());record.original_sha256[0]^=1;
    original[0]^=1; reset_output();denied(decode());original[0]^=1;
    compressed[0]^=1; reset_output();denied(decode());compressed[0]^=1;
    reset_output();denied(swapz_zswap_import_decode(&record,&authority,
        compressed,record.compressed_length,scratch,sizeof(scratch),out,4095,original));
    reset_output();denied(swapz_zswap_import_decode(&record,&authority,
        compressed,record.compressed_length,out,sizeof(out),out,sizeof(out),original));
    reset_output(); denied(swapz_zswap_import_decode(&record,&authority,
        compressed,record.compressed_length,out+1,4096,out,4096,original));
    /* A real LZ4 frame must never be misinterpreted as the raw block ABI. */
    const swapz_u8 original_payload[4]={0x04,0x22,0x4d,0x18};
    memcpy(compressed,original_payload,sizeof(original_payload));
    record.compressed_length=4;record.compressed_crc32c=swapz_crc32c_bytes(compressed,4);
    authority.actual_lower_read_bytes=4;
    reset_output();denied(decode());
    puts("ROUND022_CONSUMER_ROOTLESS_SOURCE_ONLY_PASS");
    return 0;
}
