#!/usr/bin/env python3
"""Pinned original lock-order audit; not a kernel execution or a slot count."""
from __future__ import annotations

import argparse
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
prior = runpy.run_path(str(HERE / "round050-original-deferred-slot-source-audit.py"),
                       run_name="round054_pristine_dependency")

# New ordered anchors: actual allocation barrier, interrupted swapoff reopen,
# swapcache retirement with surviving count, and normal folio write completion.
SPECS = [
    [
        "mm/swapfile.c",
        "static void wait_for_allocation(struct swap_info_struct *si)",
        [
            "BUG_ON(si->flags & SWP_WRITEOK);",
            "for (offset = 0; offset < end; offset += SWAPFILE_CLUSTER) {",
            "ci = swap_cluster_lock(si, offset);",
            "swap_cluster_unlock(ci);"
        ]
    ],
    [
        "mm/swapfile.c",
        "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)",
        [
            "spin_lock(&p->lock);\n\tdel_from_avail_list(p, true);",
            "spin_unlock(&p->lock);\n\tspin_unlock(&swap_lock);\n\n\twait_for_allocation(p);",
            "set_current_oom_origin();",
            "err = try_to_unuse(p->type);",
            "clear_current_oom_origin();",
            "if (err) {",
            "reinsert_swap_info(p);",
            "percpu_ref_kill(&p->users);"
        ]
    ],
    [
        "mm/swapfile.c",
        "static void reinsert_swap_info(struct swap_info_struct *si)",
        [
            "spin_lock(&swap_lock);",
            "spin_lock(&si->lock);",
            "_enable_swap_info(si);",
            "spin_unlock(&si->lock);",
            "spin_unlock(&swap_lock);"
        ]
    ],
    [
        "mm/swap_state.c",
        "static void __swap_cache_do_del_folio(struct swap_cluster_info *ci,",
        [
            "VM_WARN_ON_ONCE_FOLIO(!folio_test_locked(folio), folio);",
            "if (__swp_tb_get_count(old_tb))",
            "folio_swapped = true;",
            "__swap_table_set(ci, ci_off, shadow_to_swp_tb(shadow,\n\t\t\t\t __swp_tb_get_flags(old_tb)));",
            "folio->swap.val = 0;",
            "folio_clear_swapcache(folio);",
            "if (!folio_swapped) {",
            "__swap_cluster_free_entries(si, ci, ci_start, nr_pages);"
        ]
    ],
    [
        "mm/page_io.c",
        "static void swap_write_end(struct swap_iocb *sio, bool failed)",
        [
            "if (failed) {",
            "folio_mark_dirty(folio);",
            "folio_clear_reclaim(folio);",
            "folio_end_writeback(folio);",
            "mempool_free(sio, sio_pool);"
        ]
    ]
]
MUTATIONS = [[0,0],[0,1],[0,2],[0,3],[1,1],[1,4],[2,2],[3,1],[3,3],[3,4],[3,5],[4,1],[4,3],[4,4]]


def verify(sources: dict[str, str]) -> None:
    for path, signature, tokens in SPECS:
        region = prior["function"](sources, path, signature)
        offset = 0
        for token in tokens:
            position = region.find(token, offset)
            if position < 0:
                raise ValueError("original_lock_order:" + path + ":" + token)
            offset = position + len(token)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        sources = prior["pristine_original"](args.linux_root)
        verify(sources)
        for function_index, token_index in MUTATIONS:
            path, signature, tokens = SPECS[function_index]
            region = prior["function"](sources, path, signature)
            token = tokens[token_index]
            if region.count(token) != 1 or sources[path].count(region) != 1:
                raise ValueError("nonunique_real_source_mutation:" + token)
            revised = region.replace(token, "/* Round054 hostile removed transition */", 1)
            mutated = dict(sources)
            mutated[path] = sources[path].replace(region, revised, 1)
            if mutated == sources:
                raise ValueError("unchanged_real_source_mutation:" + token)
            try:
                verify(mutated)
            except ValueError:
                continue
            raise ValueError("surviving_real_source_mutation:" + token)
    except (ValueError, OSError, prior["DeferredSwapSlotAuditError"]) as error:
        print("ROUND054_PRISTINE_LOCK_ORDER_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND054_PRISTINE_ORIGINAL_14_NEW_SOURCE_HOSTILES_PASS "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
