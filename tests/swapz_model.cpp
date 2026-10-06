// SPDX-License-Identifier: GPL-2.0-only
#include <lz4.h>

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
               std::uint32_t minimum_slack = 4)
        : logical_pages_(logical_pages), physical_(physical_blocks), mappings_(logical_pages) {
        const std::uint32_t slack = std::max(minimum_slack, (logical_pages + 3U) / 4U);
        const std::uint32_t minimum_arena = logical_pages + slack;
        arena_count_ = physical_blocks / minimum_arena;
        if (arena_count_ < 2) throw std::invalid_argument("need >=2 arenas");
        arena_blocks_ = physical_blocks / arena_count_;
        if (arena_blocks_ < minimum_arena) throw std::logic_error("unsafe arena geometry");
        reset_pack();
    }

    void write(std::uint32_t logical_page, const Page &page) {
        if (logical_page >= logical_pages_) throw std::out_of_range("logical page");
        ++logical_writes_;
        std::array<char, kBlockBytes> compressed{};
        const int length = LZ4_compress_fast(page.data(), compressed.data(),
                                             static_cast<int>(page.size()), kCompressLimit, 1);
        if (length > 0) {
            ensure_pack_block();
            if (pack_count_ == kMaxRecords || pack_end_ + static_cast<std::size_t>(length) > kBlockBytes) {
                flush();
                ensure_pack_block();
            }
            auto *header = reinterpret_cast<ContainerDisk *>(pack_.data());
            const std::size_t index = pack_count_;
            header->records[index] = RecordDisk{logical_page,
                static_cast<std::uint16_t>(pack_end_), static_cast<std::uint16_t>(length)};
            std::memcpy(pack_.data() + pack_end_, compressed.data(), static_cast<std::size_t>(length));
            pending_.push_back(logical_page);
            pack_end_ += static_cast<std::size_t>(length);
            ++pack_count_;
            ++compressed_pages_;
        } else {
            flush();
            ensure_block();
            const std::uint32_t block = current_physical_block();
            physical_[block] = page;
            mappings_[logical_page] = Mapping{block, static_cast<std::uint16_t>(kBlockBytes), 0, kValid};
            ++head_;
            ++physical_writes_;
            ++raw_pages_;
        }
    }

    void flush() {
        if (pack_count_ == 0) return;
        ensure_block();
        auto *header = reinterpret_cast<ContainerDisk *>(pack_.data());
        header->magic = kMagic;
        header->version = 1;
        header->count = static_cast<std::uint16_t>(pack_count_);
        const std::uint32_t block = current_physical_block();
        physical_[block] = pack_;
        for (std::size_t index = 0; index < pending_.size(); ++index) {
            const auto &record = header->records[index];
            mappings_[pending_[index]] = Mapping{block, record.length,
                static_cast<std::uint8_t>(index), static_cast<std::uint8_t>(kValid | kCompressed)};
        }
        ++head_;
        ++physical_writes_;
        reset_pack();
    }

    Page read(std::uint32_t logical_page) {
        flush();
        Page output{};
        const Mapping mapping = mappings_.at(logical_page);
        if (!(mapping.flags & kValid)) return output;
        ++physical_reads_;
        if (!(mapping.flags & kCompressed)) return physical_.at(mapping.block);
        const Page &container_page = physical_.at(mapping.block);
        const auto *header = reinterpret_cast<const ContainerDisk *>(container_page.data());
        if (header->magic != kMagic || mapping.record >= header->count) throw std::runtime_error("bad container");
        const RecordDisk &record = header->records[mapping.record];
        if (record.logical_page != logical_page || record.length != mapping.length) throw std::runtime_error("bad record");
        const int decoded = LZ4_decompress_safe(container_page.data() + record.offset, output.data(),
                                                record.length, static_cast<int>(output.size()));
        if (decoded != static_cast<int>(output.size())) throw std::runtime_error("decompression failed");
        return output;
    }

    void discard(std::uint32_t logical_page) { mappings_.at(logical_page) = {}; }

    std::uint64_t logical_write_bytes() const { return logical_writes_ * kBlockBytes; }
    std::uint64_t physical_write_bytes() const { return physical_writes_ * kBlockBytes; }
    std::uint64_t rotations() const { return rotations_; }
    std::uint64_t raw_pages() const { return raw_pages_; }
    std::uint64_t compressed_pages() const { return compressed_pages_; }
    std::uint32_t arena_count() const { return arena_count_; }

private:
    void reset_pack() {
        pack_.fill(0);
        pack_end_ = kHeaderBytes;
        pack_count_ = 0;
        pending_.clear();
    }

    std::uint32_t current_physical_block() const { return current_arena_ * arena_blocks_ + head_; }

    void ensure_pack_block() {
        if (pack_count_ == 0) ensure_block();
    }

    void ensure_block() {
        if (head_ < arena_blocks_) return;
        rotate();
    }

    Page read_without_flush(std::uint32_t logical_page) {
        Page output{};
        const Mapping mapping = mappings_.at(logical_page);
        if (!(mapping.flags & kValid)) return output;
        ++physical_reads_;
        if (!(mapping.flags & kCompressed)) return physical_.at(mapping.block);
        const Page &container_page = physical_.at(mapping.block);
        const auto *header = reinterpret_cast<const ContainerDisk *>(container_page.data());
        const RecordDisk &record = header->records[mapping.record];
        const int decoded = LZ4_decompress_safe(container_page.data() + record.offset, output.data(),
                                                record.length, static_cast<int>(output.size()));
        if (decoded != static_cast<int>(output.size())) throw std::runtime_error("compaction decode failed");
        return output;
    }

    void rotate() {
        if (pack_count_ != 0) throw std::logic_error("rotate with pending pack");
        const std::uint32_t old_arena = current_arena_;
        current_arena_ = (current_arena_ + 1U) % arena_count_;
        head_ = 0;
        ++rotations_;
        for (std::uint32_t logical_page = 0; logical_page < logical_pages_; ++logical_page) {
            const Mapping old = mappings_[logical_page];
            if (!(old.flags & kValid)) continue;
            if (old.block / arena_blocks_ != old_arena) throw std::logic_error("arena invariant");
            const Page page = read_without_flush(logical_page);
            write_compaction(logical_page, page);
        }
        flush();
        if (head_ >= arena_blocks_) throw std::logic_error("compaction consumed arena slack");
    }

    void write_compaction(std::uint32_t logical_page, const Page &page) {
        std::array<char, kBlockBytes> compressed{};
        const int length = LZ4_compress_fast(page.data(), compressed.data(),
                                             static_cast<int>(page.size()), kCompressLimit, 1);
        if (length > 0) {
            if (pack_count_ == kMaxRecords || pack_end_ + static_cast<std::size_t>(length) > kBlockBytes) flush();
            if (head_ >= arena_blocks_) throw std::logic_error("no compaction space");
            auto *header = reinterpret_cast<ContainerDisk *>(pack_.data());
            const std::size_t index = pack_count_;
            header->records[index] = RecordDisk{logical_page, static_cast<std::uint16_t>(pack_end_),
                                                static_cast<std::uint16_t>(length)};
            std::memcpy(pack_.data() + pack_end_, compressed.data(), static_cast<std::size_t>(length));
            pending_.push_back(logical_page);
            pack_end_ += static_cast<std::size_t>(length);
            ++pack_count_;
        } else {
            flush();
            if (head_ >= arena_blocks_) throw std::logic_error("no raw compaction space");
            const std::uint32_t block = current_physical_block();
            physical_[block] = page;
            mappings_[logical_page] = Mapping{block, static_cast<std::uint16_t>(kBlockBytes), 0, kValid};
            ++head_;
            ++physical_writes_;
        }
    }

    std::uint32_t logical_pages_{};
    std::vector<Page> physical_;
    std::vector<Mapping> mappings_;
    std::uint32_t arena_blocks_{};
    std::uint32_t arena_count_{};
    std::uint32_t current_arena_{};
    std::uint32_t head_{};
    Page pack_{};
    std::size_t pack_end_{};
    std::size_t pack_count_{};
    std::vector<std::uint32_t> pending_;
    std::uint64_t logical_writes_{};
    std::uint64_t physical_writes_{};
    std::uint64_t physical_reads_{};
    std::uint64_t rotations_{};
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
    for (char &byte : page) byte = static_cast<char>(distribution(generator));
    return page;
}

void test_compression_reduces_writes() {
    SwapzModel model(64, 256);
    std::vector<Page> expected(64);
    for (std::uint32_t page = 0; page < 64; ++page) {
        expected[page] = compressible_page(page);
        model.write(page, expected[page]);
    }
    model.flush();
    assert(model.physical_write_bytes() < model.logical_write_bytes() / 2);
    for (std::uint32_t page = 0; page < 64; ++page) assert(model.read(page) == expected[page]);
}

void test_raw_round_trip() {
    SwapzModel model(32, 128);
    std::mt19937 generator(0x12345678U);
    std::vector<Page> expected(32);
    for (std::uint32_t page = 0; page < 32; ++page) {
        expected[page] = random_page(generator);
        model.write(page, expected[page]);
    }
    model.flush();
    assert(model.raw_pages() >= 28);
    for (std::uint32_t page = 0; page < 32; ++page) assert(model.read(page) == expected[page]);
}

void test_rewrite_and_discard() {
    SwapzModel model(32, 160);
    Page first = compressible_page(1);
    Page second = compressible_page(9);
    model.write(7, first);
    model.write(7, second);
    model.flush();
    assert(model.read(7) == second);
    model.discard(7);
    assert(model.read(7) == Page{});
}

void test_rotation_preserves_latest_data() {
    SwapzModel model(24, 144);
    std::vector<Page> expected(24);
    for (std::uint32_t round = 0; round < 20; ++round) {
        for (std::uint32_t page = 0; page < 24; ++page) {
            expected[page] = compressible_page(round * 31U + page);
            model.write(page, expected[page]);
        }
        model.flush();
    }
    assert(model.rotations() > 0);
    for (std::uint32_t page = 0; page < 24; ++page) assert(model.read(page) == expected[page]);
}

void test_pack_boundary_rotation() {
    SwapzModel model(16, 96);
    std::vector<Page> expected(16);
    std::mt19937 generator(0xabcdef01U);
    for (std::uint32_t round = 0; round < 40; ++round) {
        for (std::uint32_t page = 0; page < 16; ++page) {
            expected[page] = (page % 3U == 0U) ? random_page(generator) : compressible_page(round + page);
            model.write(page, expected[page]);
        }
        model.flush();
    }
    assert(model.rotations() > 2);
    for (std::uint32_t page = 0; page < 16; ++page) assert(model.read(page) == expected[page]);
}

void test_randomized_rewrite_discard_read() {
    SwapzModel model(48, 288);
    std::vector<Page> expected(48);
    std::vector<bool> valid(48, false);
    std::mt19937 generator(0x45be129aU);
    std::uniform_int_distribution<std::uint32_t> page_distribution(0, 47);
    std::uniform_int_distribution<int> operation_distribution(0, 99);
    for (std::uint32_t operation = 0; operation < 5000; ++operation) {
        const std::uint32_t page = page_distribution(generator);
        const int choice = operation_distribution(generator);
        if (choice < 70) {
            expected[page] = (choice < 50) ? compressible_page(operation + page) : random_page(generator);
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
    assert(model.rotations() > 0);
}

} // namespace

int main() {
    test_compression_reduces_writes();
    test_raw_round_trip();
    test_rewrite_and_discard();
    test_rotation_preserves_latest_data();
    test_pack_boundary_rotation();
    test_randomized_rewrite_discard_read();
    std::cout << "swapz model tests: PASS\n";
    return 0;
}
