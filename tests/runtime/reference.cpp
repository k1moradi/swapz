#include <linux/fs.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <random>
#include <string>
#include <thread>
#include <vector>

using Page = std::array<unsigned char, 4096>;

static void fail(const char *what) {
    std::cerr << what << ": " << std::strerror(errno) << '\n';
    std::exit(2);
}
static void exact_pwrite(int fd, const void *data, std::size_t size, off_t off) {
    auto *p = static_cast<const unsigned char *>(data);
    while (size) {
        ssize_t n = pwrite(fd, p, size, off);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) fail("pwrite");
        p += n; off += n; size -= static_cast<std::size_t>(n);
    }
}
static void exact_pread(int fd, void *data, std::size_t size, off_t off) {
    auto *p = static_cast<unsigned char *>(data);
    while (size) {
        ssize_t n = pread(fd, p, size, off);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) fail("pread");
        p += n; off += n; size -= static_cast<std::size_t>(n);
    }
}
static void alloc_page(void **p) {
    if (posix_memalign(p, 4096, 4096) != 0) {
        std::cerr << "posix_memalign failed\n";
        std::exit(2);
    }
}
static void write_page(int fd, const Page &page, std::uint32_t index, void *aligned) {
    std::memcpy(aligned, page.data(), page.size());
    exact_pwrite(fd, aligned, page.size(), static_cast<off_t>(index) * 4096);
}
static void read_page(int fd, Page &page, std::uint32_t index, void *aligned) {
    exact_pread(fd, aligned, page.size(), static_cast<off_t>(index) * 4096);
    std::memcpy(page.data(), aligned, page.size());
}
static Page compressible(std::uint32_t index) {
    Page p{};
    const unsigned base = index & 15U;
    for (std::size_t i = 0; i < p.size(); ++i)
        p[i] = static_cast<unsigned char>((base + (i / 128U)) & 15U);
    return p;
}
static Page random_page(std::mt19937 &rng) {
    Page p{};
    std::uniform_int_distribution<unsigned> bytes(0, 255);
    for (auto &b : p) b = static_cast<unsigned char>(bytes(rng));
    return p;
}
static bool verify_page(int fd, const std::vector<Page> &expected,
                        std::uint32_t index, void *aligned) {
    Page actual{};
    read_page(fd, actual, index, aligned);
    if (actual != expected[index]) {
        std::cerr << "read mismatch page=" << index << '\n';
        return false;
    }
    return true;
}
static int open_device(const char *path) {
    int fd = open(path, O_RDWR | O_DIRECT | O_CLOEXEC);
    if (fd < 0) fail("open");
    return fd;
}
static int random_run(const char *path, unsigned long seed, std::uint32_t operations) {
    constexpr std::uint32_t pages = 512;
    std::vector<Page> expected(pages);
    std::vector<bool> valid(pages, false);
    std::mt19937 rng(static_cast<std::mt19937::result_type>(seed));
    std::uniform_int_distribution<std::uint32_t> page_dist(0, pages - 1);
    std::uniform_int_distribution<unsigned> op_dist(0, 99);
    std::uniform_int_distribution<std::uint32_t> range_dist(1, 4);
    std::uniform_int_distribution<unsigned> byte_dist(0, 255);
    std::uniform_int_distribution<unsigned> nibble_dist(0, 15);
    void *aligned = nullptr; alloc_page(&aligned);
    int fd = open_device(path);
    std::uint64_t writes=0, rewrites=0, reads=0, flushes=0, discards=0;
    std::uint64_t discard_pages=0, comp=0, raw=0;
    for (std::uint32_t op=0; op<operations; ++op) {
        const std::uint32_t page=page_dist(rng);
        const unsigned choice=op_dist(rng);
        if (choice<55) {
            Page next{};
            const bool use_comp=(op_dist(rng)%4)!=0;
            if (use_comp) {
                const unsigned base=nibble_dist(rng);
                for (std::size_t i=0;i<next.size();++i)
                    next[i]=static_cast<unsigned char>((base+(i/128U))&15U);
                ++comp;
            } else {
                for (auto &b:next) b=static_cast<unsigned char>(byte_dist(rng));
                ++raw;
            }
            if (valid[page]) ++rewrites; else ++writes;
            write_page(fd,next,page,aligned); expected[page]=next; valid[page]=true; ++writes;
        } else if (choice<74) {
            Page actual{}; read_page(fd,actual,page,aligned);
            if (actual!=expected[page]) { std::cerr<<"read mismatch operation="<<op<<" page="<<page<<"\n"; return 3; }
            ++reads;
        } else if (choice<81) {
            if (fsync(fd)!=0) fail("fsync");
            ++flushes;
        } else {
            const std::uint32_t count=std::min(range_dist(rng),pages-page);
            std::uint64_t range[2]{static_cast<std::uint64_t>(page)*4096,
                                   static_cast<std::uint64_t>(count)*4096};
            if (ioctl(fd,BLKDISCARD,&range)!=0) fail("BLKDISCARD");
            for (std::uint32_t i=0;i<count;++i) { valid[page+i]=false; expected[page+i].fill(0); }
            ++discards; discard_pages+=count;
        }
    }
    if (fsync(fd)!=0) fail("final fsync");
    for (std::uint32_t i=0;i<pages;++i) if(!verify_page(fd,expected,i,aligned)) return 3;
    close(fd); free(aligned);
    std::cout<<"seed="<<seed<<" operations="<<operations<<" writes="<<writes
             <<" rewrites="<<rewrites<<" reads="<<reads<<" flushes="<<flushes
             <<" discard_ranges="<<discards<<" discard_pages="<<discard_pages
             <<" compressible_writes="<<comp<<" incompressible_writes="<<raw
             <<" readback=PASS\n";
    return 0;
}
static int live_run(const char *path, std::uint32_t operations) {
    constexpr std::uint32_t pages=256;
    std::vector<Page> expected(pages);
    void *aligned=nullptr; alloc_page(&aligned);
    int fd=open_device(path);
    for(std::uint32_t i=0;i<8;++i){expected[i]=compressible(i+1);write_page(fd,expected[i],i,aligned);}
    std::mt19937 rng(0x44b1a73U);
    expected[200]=random_page(rng); write_page(fd,expected[200],200,aligned);
    std::uint64_t range[2]{200ULL*4096,4096};
    if(ioctl(fd,BLKDISCARD,&range)!=0) fail("live discard");
    expected[200].fill(0);
    std::uint32_t checkpoints=0;
    for(std::uint32_t i=0;i<operations;++i){
        expected[8]=random_page(rng); write_page(fd,expected[8],8,aligned);
        if((i+1)%256==0){
            if(fsync(fd)!=0)fail("live checkpoint fsync");
            for(std::uint32_t p=0;p<pages;++p)if(!verify_page(fd,expected,p,aligned))return 3;
            ++checkpoints;
        }
    }
    if(fsync(fd)!=0)fail("live final fsync");
    for(std::uint32_t p=0;p<pages;++p)if(!verify_page(fd,expected,p,aligned))return 3;
    close(fd);free(aligned);
    std::cout<<"live_ops="<<operations<<" checkpoints="<<checkpoints<<" pages="<<pages<<" readback=PASS\n";
    return 0;
}
static int selectivity_run(const char *path) {
    constexpr std::uint32_t pages=8192;
    std::vector<Page> expected(pages);
    void *aligned=nullptr;alloc_page(&aligned);
    int fd=open_device(path);
    std::mt19937 rng(0x6b77c1a9U);
    for(std::uint32_t segment=0;segment<39;++segment){
        for(std::uint32_t i=0;i<64;++i){
            const std::uint32_t page=segment*64+i;
            expected[page]=compressible(page+1);write_page(fd,expected[page],page,aligned);
        }
        for(std::uint32_t i=0;i<192;++i){
            expected[4096]=random_page(rng);write_page(fd,expected[4096],4096,aligned);
        }
    }
    expected[5000]=random_page(rng);write_page(fd,expected[5000],5000,aligned);
    if(fsync(fd)!=0)fail("selectivity fsync");
    for(std::uint32_t p=0;p<pages;++p)if(!verify_page(fd,expected,p,aligned))return 3;
    close(fd);free(aligned);
    std::cout<<"selectivity_pages="<<pages<<" cold_live_pages=2496 readback=PASS\n";
    return 0;
}
static int group_run(const char *path, std::uint32_t live_records) {
    constexpr std::uint32_t pages=512;
    std::vector<Page> expected(pages);
    void *aligned=nullptr;alloc_page(&aligned);
    int fd=open_device(path);
    if(fsync(fd)!=0)fail("group initial fsync");
    std::mt19937 rng(0x91d5e7U);
    for(std::uint32_t page=8;page<263;++page){expected[page]=random_page(rng);write_page(fd,expected[page],page,aligned);}
    if(live_records<8){
        std::uint64_t range[2]{static_cast<std::uint64_t>(live_records)*4096,
                               static_cast<std::uint64_t>(8-live_records)*4096};
        if(ioctl(fd,BLKDISCARD,&range)!=0)fail("group source discard");
        for(std::uint32_t page=live_records;page<8;++page)expected[page].fill(0);
    }
    std::uint64_t filler_range[2]{8ULL*4096,255ULL*4096};
    if(ioctl(fd,BLKDISCARD,&filler_range)!=0)fail("group filler discard");
    for(std::uint32_t page=8;page<263;++page)expected[page].fill(0);
    for(std::uint32_t page=263;page<512;++page){expected[page]=random_page(rng);write_page(fd,expected[page],page,aligned);}
    for(std::uint32_t i=0;i<7;++i){expected[511]=random_page(rng);write_page(fd,expected[511],511,aligned);}
    expected[511]=random_page(rng);write_page(fd,expected[511],511,aligned);
    for(std::uint32_t i=0;i<255;++i){expected[511]=random_page(rng);write_page(fd,expected[511],511,aligned);}
    expected[511]=random_page(rng);write_page(fd,expected[511],511,aligned);
    if(fsync(fd)!=0)fail("group final fsync");
    for(std::uint32_t p=8;p<pages;++p)if(!verify_page(fd,expected,p,aligned))return 3;
    close(fd);free(aligned);
    std::cout<<"group_live="<<live_records<<" source_records=8 rest_readback=PASS\n";
    return 0;
}
int main(int argc,char **argv){
    if(argc<3){std::cerr<<"usage: reference MODE DEVICE [ARG]\n";return 2;}
    std::string mode=argv[1];
    if(mode=="random"&&argc==5)return random_run(argv[2],std::stoul(argv[3],nullptr,0),static_cast<std::uint32_t>(std::stoul(argv[4])));
    if(mode=="live"&&argc==4)return live_run(argv[2],static_cast<std::uint32_t>(std::stoul(argv[3])));
    if(mode=="selectivity"&&argc==3)return selectivity_run(argv[2]);
    if(mode=="group"&&argc==4)return group_run(argv[2],static_cast<std::uint32_t>(std::stoul(argv[3])));
    std::cerr<<"bad arguments\n";return 2;
}
