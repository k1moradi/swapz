static void reset_fixture(void) {
    memset(&swap_cache, 0, sizeof(swap_cache));
    memset(&observed_bio, 0, sizeof(observed_bio));
    stored_entries.entry = NULL;
    device_available = true;
    cache_available = true;
    decompression_success = true;
    decompress_count = erase_count = free_count = write_count = submit_count = cleanup_count = 0;
}
int main(void) {
    struct obj_cgroup object_cgroup = {0};
    struct zswap_entry stored_entry = {.swpentry = {.val = 17},
        .objcg = &object_cgroup, .compressed_length = 128};
    struct zswap_entry recycled_entry = {.swpentry = {.val = 17},
        .objcg = NULL, .compressed_length = 64};
    swp_entry_t identity = {.val = 17};
    for (size_t i = 0; i < PAGE_SIZE; ++i) original_page[i] = (unsigned char)(i % 251U);

    reset_fixture();
    stored_entries.entry = &stored_entry;
    assert(zswap_writeback_entry(&stored_entry, identity) == 0);
    assert(decompress_count == 1 && erase_count == 1 && free_count == 1);
    assert(write_count == 1 && submit_count == 1 && cleanup_count == 0);
    assert(stored_entries.entry == NULL && stored_entry.freed && object_cgroup.events == 1);
    assert(observed_bio.operation == (REQ_OP_WRITE | REQ_SWAP));
    assert(observed_bio.length == PAGE_SIZE);
    assert(observed_bio.swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK);
    assert(memcmp(original_page, swap_cache.bytes, PAGE_SIZE) == 0);
    struct bio carrier = {.bi_opf = observed_bio.operation,
        .bi_swap_origin = observed_bio.swap_origin};
    assert(bio_is_zswap_stored_writeback(&carrier));
    carrier.bi_opf = REQ_OP_READ | REQ_SWAP;
    assert(!bio_is_zswap_stored_writeback(&carrier));
    carrier.bi_opf = REQ_OP_WRITE;
    assert(!bio_is_zswap_stored_writeback(&carrier));
    carrier.bi_opf = REQ_OP_WRITE | REQ_SWAP;
    carrier.bi_swap_origin = 0;
    assert(!bio_is_zswap_stored_writeback(&carrier));
    carrier.bi_swap_origin = 2;
    assert(!bio_is_zswap_stored_writeback(&carrier));

    reset_fixture();
    stored_entry.freed = false;
    stored_entries.entry = &recycled_entry; /* Stale slot generation. */
    assert(zswap_writeback_entry(&stored_entry, identity) == -ENOMEM);
    assert(decompress_count == 0 && erase_count == 0 && free_count == 0);
    assert(write_count == 0 && submit_count == 0 && cleanup_count == 1);
    assert(!stored_entry.freed && stored_entries.entry == &recycled_entry);

    reset_fixture();
    stored_entries.entry = &stored_entry;
    decompression_success = false;
    assert(zswap_writeback_entry(&stored_entry, identity) == -EIO);
    assert(decompress_count == 1 && erase_count == 0 && free_count == 0);
    assert(write_count == 0 && submit_count == 0 && cleanup_count == 1);
    assert(!stored_entry.freed && stored_entries.entry == &stored_entry);

    reset_fixture();
    stored_entries.entry = &stored_entry;
    device_available = false;
    assert(zswap_writeback_entry(&stored_entry, identity) == -ENOENT);
    assert(decompress_count == 0 && erase_count == 0 && write_count == 0);

    reset_fixture();
    stored_entries.entry = &stored_entry;
    cache_available = false;
    assert(zswap_writeback_entry(&stored_entry, identity) == -ENOMEM);
    assert(decompress_count == 0 && erase_count == 0 && write_count == 0);

    reset_fixture();
    stored_entries.entry = &stored_entry;
    stored_entry.compressed_length = 0;
    assert(zswap_writeback_entry(&stored_entry, identity) == -EIO);
    assert(write_count == 0 && free_count == 0 && cleanup_count == 1);
    return 0;
}
