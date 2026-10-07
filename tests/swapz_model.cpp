// SPDX-License-Identifier: GPL-2.0-only
#include <lz4.h>

#include <algorithm>
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <vector>

namespace {
constexpr std::size_t kBlockBytes = 4096;
constexpr std::size_t kMaxRecords = 8;
constexpr std::uint32_t kInvalidBlock = std::numeric_limits<std::uint32_t>::max();
constexpr std::uint8_t kValid = 1U << 0;
constexpr std::uint8_t kCompressed = 1U << 1;
constexpr std::size_t kMinSaving = 512;

constexpr std::uint8_t kSegmentFree = 0;
constexpr std::uint8_t kSegmentOpen = 1;
constexpr std::uint8_t kSegmentClosed = 2;
constexpr std::uint8_t kSegmentCleaning = 3;

#pragma pack(push, 1)
struct RecordDisk {
    std::uint32_t logical_page;
    std::uint16_t offset;
    std::uint16_t length;
};
struct ContainerDisk {
    std::uint32_t magic;
    std::uint16_t version;
    std::uint16_t count;
    RecordDisk records[kMaxRecords];
};
#pragma pack(pop)

constexpr std::uint32_t kMagic = 0x5a575053U;
constexpr std::size_t kHeaderBytes = sizeof(ContainerDisk);
constexpr int kCompressLimit = static_cast<int>(kBlockBytes - kHeaderBytes - kMinSaving);
using Page = std::array<char, kBlockBytes>;

struct Mapping {
    std::uint32_t block{kInvalidBlock};
    std::uint16_t length{};
    std::uint8_t record{};
    std::uint8_t flags{};
};

class SwapzModel {
public:
    SwapzModel(std::uint32_t logical_pages, std::uint32_t physical_blocks,
               std::uint32_t segment_blocks = 16)
        : logical_pages_(logical_pages),
          physical_(physical_blocks),
          mappings_(logical_pages),
          block_live_records_(physical_blocks, 0),
          segment_blocks_(segment_blocks) {
        if (segment_blocks_ < 2 || physical_blocks % segment_blocks_ != 0)
            throw std::invalid_argument("physical blocks must be segment aligned");

        segment_count_ = physical_blocks / segment_blocks_;
        if (segment_count_ < 3)
            throw std::invalid_argument("need >=3 segments");

        const std::uint32_t reserve =
            std::max((logical_pages + 3U) / 4U, 2U * segment_blocks_);
        if (physical_blocks < logical_pages + reserve)
            throw std::invalid_argument("insufficient GC reserve");

        segment_live_blocks_.assign(segment_count_, 0);
        segment_state_.assign(segment_count_, kSegmentFree);
        segment_cycles_.assign(segment_count_, 0);

        segment_state_[0] = kSegmentOpen;
        segment_cycles_[0] = 1;
        free_segments_ = segment_count_ - 1;
        allocation_cursor_ = 1;
        reset_pack();
    }

    void write(std::uint32_t logical_page, const Page &page) {
        if (logical_page >= logical_pages_)
            throw std::out_of_range("logical page");

        ++logical_writes_;
        store_page(logical_page, page, false, true);
    }

    void flush() { flush_pack(false, true); }

    Page read(std::uint32_t logical_page) {
        flush_pack(false, true);
        return read_mapping(logical_page, false);
    }

    void discard(std::uint32_t logical_page) {
        flush_pack(false, true);
        invalidate_mapping(logical_page);
    }

    std::uint64_t logical_write_bytes() const { return logical_writes_ * kBlockBytes; }
    std::uint64_t physical_write_bytes() const { return physical_writes_ * kBlockBytes; }
    std::uint64_t gc_write_bytes() const { return gc_writes_ * kBlockBytes; }
    std::uint64_t segment_switches() const { return segment_switches_; }
    std::uint64_t gc_pages() const { return gc_pages_; }
    std::uint64_t gc_victims() const { return gc_victims_; }
    std::uint64_t raw_pages() const { return raw_pages_; }
    std::uint64_t compressed_pages() const { return compressed_pages_; }
    std::uint32_t free_segments() const { return free_segments_; }

private:
    void reset_pack() {
        pack_.fill(0);
        pack_end_ = kHeaderBytes;
        pack_count_ = 0;
        pending_.clear();
    }

    [[nodiscard]] std::uint32_t mapping_segment(const Mapping &mapping) const {
        return mapping.block / segment_blocks_;
    }

    void unaccount_mapping(const Mapping &mapping) {
        if (!(mapping.flags & kValid))
            return;

        if (mapping.block >= physical_.size())
            throw std::logic_error("mapping block out of range");

        auto &records = block_live_records_.at(mapping.block);
        if (records == 0)
            throw std::logic_error("block live-record underflow");

        const std::uint32_t segment = mapping_segment(mapping);
        --records;
        if (records == 0) {
            auto &live_blocks = segment_live_blocks_.at(segment);
            if (live_blocks == 0)
                throw std::logic_error("segment live-block underflow");
            --live_blocks;
        }
    }

    void install_mapping(std::uint32_t logical_page, std::uint32_t block,
                         std::uint16_t length, std::uint8_t record,
                         std::uint8_t flags) {
        Mapping &mapping = mappings_.at(logical_page);
        unaccount_mapping(mapping);

        auto &records = block_live_records_.at(block);
        if (records == 0)
            ++segment_live_blocks_.at(block / segment_blocks_);
        if (records == std::numeric_limits<std::uint8_t>::max())
            throw std::logic_error("block live-record overflow");
        ++records;

        mapping = Mapping{block, length, record,
                          static_cast<std::uint8_t>(flags | kValid)};
    }

    void invalidate_mapping(std::uint32_t logical_page) {
        Mapping &mapping = mappings_.at(logical_page);
        unaccount_mapping(mapping);
        mapping = {};
    }

    [[nodiscard]] std::uint32_t current_physical_block() const {
        return current_segment_ * segment_blocks_ + head_;
    }

    [[nodiscard]] bool current_segment_has_block() const {
        return head_ < segment_blocks_;
    }

    void note_block_written(bool compaction) {
        ++head_;
        ++physical_writes_;
        if (compaction)
            ++gc_writes_;
    }

    void ensure_block(bool allow_rotation) {
        if (current_segment_has_block())
            return;
        if (!allow_rotation)
            throw std::runtime_error("GC destination overflow");
        advance_segment();
    }

    void flush_pack(bool compaction, bool allow_rotation) {
        if (pack_count_ == 0)
            return;

        ensure_block(allow_rotation);
        auto *header = reinterpret_cast<ContainerDisk *>(pack_.data());
        header->magic = kMagic;
        header->version = 1;
        header->count = static_cast<std::uint16_t>(pack_count_);
        const std::uint32_t block = current_physical_block();
        physical_.at(block) = pack_;

        for (std::size_t index = 0; index < pending_.size(); ++index) {
            const auto &record = header->records[index];
            install_mapping(pending_[index], block, record.length,
                            static_cast<std::uint8_t>(index), kCompressed);
        }

        note_block_written(compaction);
        reset_pack();
    }

    void store_page(std::uint32_t logical_page, const Page &page,
                    bool compaction, bool allow_rotation) {
        std::array<char, kBlockBytes> compressed{};
        const int length = LZ4_compress_fast(
            page.data(), compressed.data(), static_cast<int>(page.size()),
            kCompressLimit, 1);

        if (length > 0) {
            if (pack_count_ == 0)
                ensure_block(allow_rotation);

            if (pack_count_ == kMaxRecords ||
                pack_end_ + static_cast<std::size_t>(length) > kBlockBytes) {
                flush_pack(compaction, allow_rotation);
                ensure_block(allow_rotation);
            }

            auto *header = reinterpret_cast<ContainerDisk *>(pack_.data());
            const std::size_t index = pack_count_;
            header->records[index] =
                RecordDisk{logical_page, static_cast<std::uint16_t>(pack_end_),
                           static_cast<std::uint16_t>(length)};
            std::memcpy(pack_.data() + pack_end_, compressed.data(),
                        static_cast<std::size_t>(length));
            pending_.push_back(logical_page);
            pack_end_ += static_cast<std::size_t>(length);
            ++pack_count_;
            ++compressed_pages_;
            return;
        }

        flush_pack(compaction, allow_rotation);
        ensure_block(allow_rotation);
        const std::uint32_t block = current_physical_block();
        physical_.at(block) = page;
        install_mapping(logical_page, block,
                        static_cast<std::uint16_t>(kBlockBytes), 0, 0);
        note_block_written(compaction);
        ++raw_pages_;
    }

    Page read_mapping(std::uint32_t logical_page, bool compaction) {
        Page output{};
        const Mapping mapping = mappings_.at(logical_page);
        if (!(mapping.flags & kValid))
            return output;

        ++physical_reads_;
        if (compaction)
            ++gc_reads_;

        if (!(mapping.flags & kCompressed))
            return physical_.at(mapping.block);

        const Page &container_page = physical_.at(mapping.block);
        const auto *header =
            reinterpret_cast<const ContainerDisk *>(container_page.data());
        if (header->magic != kMagic || mapping.record >= header->count)
            throw std::runtime_error("bad container");

        const RecordDisk &record = header->records[mapping.record];
        if (record.logical_page != logical_page || record.length != mapping.length)
            throw std::runtime_error("bad record");

        const int decoded =
            LZ4_decompress_safe(container_page.data() + record.offset,
                                output.data(), record.length,
                                static_cast<int>(output.size()));
        if (decoded != static_cast<int>(output.size()))
            throw std::runtime_error("decompression failed");
        return output;
    }

    [[nodiscard]] std::uint32_t find_free_segment() {
        for (std::uint32_t offset = 0; offset < segment_count_; ++offset) {
            const std::uint32_t segment =
                (allocation_cursor_ + offset) % segment_count_;
            if (segment_state_[segment] != kSegmentFree)
                continue;
            allocation_cursor_ = (segment + 1U) % segment_count_;
            return segment;
        }
        throw std::runtime_error("no free segment");
    }

    [[nodiscard]] std::uint32_t choose_gc_victim() {
        std::uint32_t best = std::numeric_limits<std::uint32_t>::max();
        std::uint32_t best_live = std::numeric_limits<std::uint32_t>::max();
        const std::uint32_t headroom = std::max(1U, segment_blocks_ / 32U);

        for (std::uint32_t offset = 0; offset < segment_count_; ++offset) {
            const std::uint32_t segment = (gc_cursor_ + offset) % segment_count_;
            if (segment_state_[segment] != kSegmentClosed)
                continue;

            const std::uint32_t live = segment_live_blocks_[segment];
            if (live > segment_blocks_ - headroom || live >= best_live)
                continue;

            best = segment;
            best_live = live;
            if (live == 0)
                break;
        }

        if (best == std::numeric_limits<std::uint32_t>::max())
            throw std::runtime_error("no cleanable victim");

        gc_cursor_ = (best + 1U) % segment_count_;
        return best;
    }

    void clean_segment(std::uint32_t victim) {
        if (segment_state_.at(victim) != kSegmentClosed ||
            segment_state_.at(current_segment_) != kSegmentOpen ||
            pack_count_ != 0)
            throw std::logic_error("invalid GC state");

        segment_state_[victim] = kSegmentCleaning;
        ++gc_victims_;

        for (std::uint32_t logical_page = 0; logical_page < logical_pages_;
             ++logical_page) {
            const Mapping mapping = mappings_[logical_page];
            if (!(mapping.flags & kValid) ||
                mapping_segment(mapping) != victim)
                continue;

            const Page page = read_mapping(logical_page, true);
            store_page(logical_page, page, true, false);
            ++gc_pages_;
        }

        flush_pack(true, false);
        if (segment_live_blocks_[victim] != 0)
            throw std::logic_error("victim still has live blocks");

        segment_state_[victim] = kSegmentFree;
        ++free_segments_;
    }

    void open_free_segment() {
        const std::uint32_t segment = find_free_segment();
        segment_state_[segment] = kSegmentOpen;
        --free_segments_;
        current_segment_ = segment;
        head_ = 0;
        ++segment_cycles_[segment];
        ++segment_switches_;
    }

    void advance_segment() {
        if (pack_count_ != 0)
            throw std::logic_error("advance with pending pack");

        if (segment_state_[current_segment_] == kSegmentOpen)
            segment_state_[current_segment_] = kSegmentClosed;

        for (;;) {
            if (free_segments_ == 0)
                throw std::runtime_error("free-segment invariant lost");

            open_free_segment();

            if (free_segments_ == 0)
                clean_segment(choose_gc_victim());

            if (current_segment_has_block())
                return;

            segment_state_[current_segment_] = kSegmentClosed;
        }
    }

    std::uint32_t logical_pages_{};
    std::vector<Page> physical_;
    std::vector<Mapping> mappings_;
    std::vector<std::uint8_t> block_live_records_;
    std::uint32_t segment_blocks_{};
    std::uint32_t segment_count_{};
    std::vector<std::uint16_t> segment_live_blocks_;
    std::vector<std::uint8_t> segment_state_;
    std::vector<std::uint32_t> segment_cycles_;
    std::uint32_t current_segment_{};
    std::uint32_t head_{};
    std::uint32_t allocation_cursor_{1};
    std::uint32_t gc_cursor_{};
    std::uint32_t free_segments_{};

    Page pack_{};
    std::size_t pack_end_{};
    std::size_t pack_count_{};
    std::vector<std::uint32_t> pending_;

    std::uint64_t logical_writes_{};
    std::uint64_t physical_writes_{};
    std::uint64_t physical_reads_{};
    std::uint64_t gc_writes_{};
    std::uint64_t gc_reads_{};
    std::uint64_t segment_switches_{};
    std::uint64_t gc_pages_{};
    std::uint64_t gc_victims_{};
    std::uint64_t raw_pages_{};
    std::uint64_t compressed_pages_{};
};

Page compressible_page(std::uint32_t seed) {
    Page page{};
    for (std::size_t index = 0; index < page.size(); ++index)
        page[index] = static_cast<char>((index / 128 + seed) & 0x0fU);
    return page;
}

Page random_page(std::mt19937 &generator) {
    Page page{};
    std::uniform_int_distribution<int> distribution(0, 255);
    for (char &byte : page)
        byte = static_cast<char>(distribution(generator));
    return page;
}

void test_compression_reduces_writes() {
    SwapzModel model(64, 256, 16);
    std::vector<Page> expected(64);
    for (std::uint32_t page = 0; page < 64; ++page) {
        expected[page] = compressible_page(page);
        model.write(page, expected[page]);
    }
    model.flush();

    assert(model.physical_write_bytes() < model.logical_write_bytes() / 2);
    for (std::uint32_t page = 0; page < 64; ++page)
        assert(model.read(page) == expected[page]);
}

void test_raw_round_trip() {
    SwapzModel model(32, 128, 8);
    std::mt19937 generator(0x12345678U);
    std::vector<Page> expected(32);
    for (std::uint32_t page = 0; page < 32; ++page) {
        expected[page] = random_page(generator);
        model.write(page, expected[page]);
    }
    model.flush();

    assert(model.raw_pages() >= 28);
    for (std::uint32_t page = 0; page < 32; ++page)
        assert(model.read(page) == expected[page]);
}

void test_rewrite_and_discard() {
    SwapzModel model(24, 96, 8);
    const Page first = compressible_page(1);
    const Page second = compressible_page(9);
    model.write(7, first);
    model.write(7, second);
    model.flush();
    assert(model.read(7) == second);
    model.discard(7);
    assert(model.read(7) == Page{});
}

void test_segment_gc_preserves_latest_data() {
    SwapzModel model(24, 128, 8);
    std::vector<Page> expected(24);

    for (std::uint32_t round = 0; round < 80; ++round) {
        for (std::uint32_t page = 0; page < 24; ++page) {
            expected[page] = compressible_page(round * 31U + page);
            model.write(page, expected[page]);
        }
        model.flush();
    }

    assert(model.segment_switches() > 10);
    assert(model.gc_victims() > 0);
    for (std::uint32_t page = 0; page < 24; ++page)
        assert(model.read(page) == expected[page]);
}

void test_mixed_raw_compressed_gc() {
    /*
     * Fill three segments with raw pages.  Then rewrite 16 pages distributed
     * across all three source segments (6 + 5 + 5), so no closed source
     * segment is completely dead.  The following compressed write must open
     * the last FREE segment and clean a victim that still contains live data.
     */
    SwapzModel model(24, 48, 8);
    std::vector<Page> expected(24);
    std::mt19937 generator(0xabcdef01U);

    for (std::uint32_t page = 0; page < 24; ++page) {
        expected[page] = random_page(generator);
        model.write(page, expected[page]);
    }
    model.flush();

    constexpr std::array<std::uint32_t, 16> rewrite_pages{
        0, 1, 2, 3, 4, 5,
        8, 9, 10, 11, 12,
        16, 17, 18, 19, 20,
    };
    for (std::uint32_t page : rewrite_pages) {
        expected[page] = random_page(generator);
        model.write(page, expected[page]);
    }
    model.flush();

    /* This write triggers the first GC and also exercises compression. */
    expected[6] = compressible_page(0x61U);
    model.write(6, expected[6]);
    model.flush();

    assert(model.segment_switches() >= 3);
    assert(model.gc_victims() > 0);
    assert(model.gc_pages() > 0);
    assert(model.raw_pages() > 0);
    assert(model.compressed_pages() > 0);
    for (std::uint32_t page = 0; page < 24; ++page)
        assert(model.read(page) == expected[page]);
}

void test_gc_moves_only_victim_segment() {
    SwapzModel model(32, 160, 8);
    std::mt19937 generator(0x8d11a42bU);

    Page expected{};
    for (std::uint32_t write = 0; write < 1200; ++write) {
        expected = random_page(generator);
        model.write(0, expected);
        model.flush();
    }

    assert(model.gc_victims() > 0);
    assert(model.gc_pages() < model.segment_switches() * 4);
    assert(model.read(0) == expected);
}

void test_randomized_rewrite_discard_read() {
    SwapzModel model(48, 256, 8);
    std::vector<Page> expected(48);
    std::vector<bool> valid(48, false);
    std::mt19937 generator(0x45be129aU);
    std::uniform_int_distribution<std::uint32_t> page_distribution(0, 47);
    std::uniform_int_distribution<int> operation_distribution(0, 99);

    for (std::uint32_t operation = 0; operation < 20000; ++operation) {
        const std::uint32_t page = page_distribution(generator);
        const int choice = operation_distribution(generator);

        if (choice < 70) {
            expected[page] = (choice < 50)
                                 ? compressible_page(operation + page)
                                 : random_page(generator);
            valid[page] = true;
            model.write(page, expected[page]);
        } else if (choice < 85) {
            model.flush();
            model.discard(page);
            valid[page] = false;
        } else {
            const Page actual = model.read(page);
            assert(actual == (valid[page] ? expected[page] : Page{}));
        }
    }

    model.flush();
    for (std::uint32_t page = 0; page < 48; ++page) {
        const Page actual = model.read(page);
        assert(actual == (valid[page] ? expected[page] : Page{}));
    }

    assert(model.segment_switches() > 0);
    assert(model.gc_victims() > 0);
    assert(model.free_segments() > 0);
}

} // namespace

int main() {
    test_compression_reduces_writes();
    test_raw_round_trip();
    test_rewrite_and_discard();
    test_segment_gc_preserves_latest_data();
    test_mixed_raw_compressed_gc();
    test_gc_moves_only_victim_segment();
    test_randomized_rewrite_discard_read();
    std::cout << "swapz V2 model tests: PASS\n";
    return 0;
}
