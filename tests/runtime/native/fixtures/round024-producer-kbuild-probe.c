/* Round024 exact-source compiler probe: deliberately synthetic identities.
 * Expected success is ONLY refusing all live compressed delivery.
 */
static void round024_compiler_probe_negatives(void)
{
    struct zswap_entry entry = { .swpentry = { .val = 17 },
        .length = 256, .handle = 31 };
    struct zswap_entry old_entry = entry;
    struct folio locked = { true }, unlocked = { false };
    swp_entry_t slot = { .val = 17 };

    tree.ptr = &entry;
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &locked) == -EOPNOTSUPP);
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &unlocked) == -EOPNOTSUPP);
    assert(zswap_swapz_round024_producer_kbuild_probe(
        NULL, slot, &locked) == -EOPNOTSUPP);
    entry.handle = 0;
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &locked) == -EOPNOTSUPP);
    entry.handle = 31;
    entry.length = 0;
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &locked) == -EOPNOTSUPP);
    entry.length = 3569;
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &locked) == -EOPNOTSUPP);
    entry.length = 256;
    slot.val++;
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &locked) == -EOPNOTSUPP);
    slot.val--;
    tree.ptr = &old_entry;
    assert(zswap_swapz_round024_producer_kbuild_probe(
        &entry, slot, &locked) == -ESTALE);
    tree.ptr = NULL;
}
