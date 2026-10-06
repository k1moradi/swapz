// SPDX-License-Identifier: GPL-2.0-only
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/wait.h>
#include <linux/fs.h>
#include <fcntl.h>
#include <spawn.h>
#include <unistd.h>

#include <cerrno>
#include <charconv>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

extern char **environ;

namespace {
constexpr std::uint64_t kPageBytes = 4096;
constexpr std::uint64_t kSectorsPerPage = kPageBytes / 512;

[[noreturn]] void fail(const std::string &message) {
    throw std::runtime_error(message);
}

std::uint64_t parse_size(std::string_view text) {
    if (text.empty()) fail("empty size");
    std::uint64_t multiplier = 1;
    const char suffix = text.back();
    if (suffix < '0' || suffix > '9') {
        switch (suffix) {
        case 'K': case 'k': multiplier = 1024ULL; break;
        case 'M': case 'm': multiplier = 1024ULL * 1024ULL; break;
        case 'G': case 'g': multiplier = 1024ULL * 1024ULL * 1024ULL; break;
        case 'T': case 't': multiplier = 1024ULL * 1024ULL * 1024ULL * 1024ULL; break;
        default: fail("invalid size suffix: " + std::string(1, suffix));
        }
        text.remove_suffix(1);
    }
    std::uint64_t value{};
    const auto [end, error] = std::from_chars(text.data(), text.data() + text.size(), value);
    if (error != std::errc{} || end != text.data() + text.size()) fail("invalid size");
    if (value > UINT64_MAX / multiplier) fail("size overflows uint64");
    return value * multiplier;
}

std::uint64_t round_down_page(std::uint64_t value) {
    return value & ~(kPageBytes - 1);
}

int run_command(const std::vector<std::string> &arguments) {
    if (arguments.empty()) return EINVAL;
    std::vector<char *> argv;
    argv.reserve(arguments.size() + 1);
    for (const auto &argument : arguments) argv.push_back(const_cast<char *>(argument.c_str()));
    argv.push_back(nullptr);

    pid_t process{};
    const int spawn_error = posix_spawnp(&process, argv.front(), nullptr, nullptr, argv.data(), environ);
    if (spawn_error != 0) return spawn_error;
    int status{};
    while (waitpid(process, &status, 0) < 0) {
        if (errno != EINTR) return errno;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return ECHILD;
}

void require_success(const std::vector<std::string> &arguments, std::string_view description) {
    const int result = run_command(arguments);
    if (result != 0) fail(std::string(description) + " failed with status " + std::to_string(result));
}

std::uint64_t block_device_size(const std::filesystem::path &device) {
    const int descriptor = open(device.c_str(), O_RDONLY | O_CLOEXEC);
    if (descriptor < 0) fail("cannot open " + device.string() + ": " + std::strerror(errno));
    std::uint64_t bytes{};
    const int result = ioctl(descriptor, BLKGETSIZE64, &bytes);
    const int saved_errno = errno;
    close(descriptor);
    if (result < 0) fail("BLKGETSIZE64 failed: " + std::string(std::strerror(saved_errno)));
    return bytes;
}

struct DeviceIdentity { unsigned int major_number{}; unsigned int minor_number{}; };

DeviceIdentity device_identity(const std::filesystem::path &device) {
    struct stat info{};
    if (stat(device.c_str(), &info) != 0) fail("cannot stat " + device.string());
    if (!S_ISBLK(info.st_mode)) fail(device.string() + " is not a block device");
    return {static_cast<unsigned int>(major(info.st_rdev)), static_cast<unsigned int>(minor(info.st_rdev))};
}

bool device_is_mounted(const DeviceIdentity &identity) {
    std::ifstream input("/proc/self/mountinfo");
    std::string line;
    const std::string needle = std::to_string(identity.major_number) + ":" + std::to_string(identity.minor_number);
    while (std::getline(input, line)) {
        std::istringstream stream(line);
        std::string mount_id, parent_id, device_number;
        if (stream >> mount_id >> parent_id >> device_number && device_number == needle) return true;
    }
    return false;
}

bool path_is_active_swap(const std::filesystem::path &path) {
    std::error_code error;
    const auto canonical = std::filesystem::weakly_canonical(path, error);
    std::ifstream input("/proc/swaps");
    std::string line;
    std::getline(input, line); // header
    while (std::getline(input, line)) {
        std::istringstream stream(line);
        std::string source;
        if (!(stream >> source)) continue;
        std::error_code source_error;
        const auto source_canonical = std::filesystem::weakly_canonical(source, source_error);
        if (!source_error && !error && source_canonical == canonical) return true;
        if (source == path) return true;
    }
    return false;
}

std::filesystem::path mapper_path(std::string_view name) {
    return std::filesystem::path("/dev/mapper") / std::string(name);
}

struct StartOptions {
    std::filesystem::path backing;
    std::string name{"swapz0"};
    std::optional<std::uint64_t> logical_bytes;
    int priority{100};
    bool upper_discard{true};
};

void start(const StartOptions &options) {
    if (geteuid() != 0) fail("start requires root");
    const auto identity = device_identity(options.backing);
    if (device_is_mounted(identity)) fail("backing device is mounted; refusing destructive use");
    if (path_is_active_swap(options.backing)) fail("backing device is already active as swap");

    const std::uint64_t physical_bytes = round_down_page(block_device_size(options.backing));
    std::uint64_t logical_bytes = options.logical_bytes.value_or(round_down_page(physical_bytes / 3));
    logical_bytes = round_down_page(logical_bytes);
    if (logical_bytes < 64ULL * 1024ULL * 1024ULL) fail("logical swap size must be at least 64 MiB");

    constexpr std::uint64_t kSegmentBytes = 1024ULL * 1024ULL;
    const std::uint64_t ratio_reserve = (logical_bytes + 3ULL) / 4ULL;
    const std::uint64_t minimum_reserve =
        ratio_reserve > 2ULL * kSegmentBytes ? ratio_reserve : 2ULL * kSegmentBytes;
    if (logical_bytes > physical_bytes || minimum_reserve > physical_bytes - logical_bytes) {
        fail("V2 requires >=25% logical-size reserve and at least two 1 MiB segments");
    }

    const std::uint64_t logical_sectors = logical_bytes / 512;
    const std::string table = "0 " + std::to_string(logical_sectors) + " swapz " + options.backing.string();

    require_success({"modprobe", "dm-swapz"}, "loading dm-swapz");
    require_success({"dmsetup", "create", options.name, "--table", table}, "creating swapz mapping");
    const auto mapped = mapper_path(options.name);

    try {
        require_success({"mkswap", "-f", mapped.string()}, "mkswap");
        std::vector<std::string> swapon_arguments{"swapon", "--priority", std::to_string(options.priority)};
        if (options.upper_discard) {
            auto discard_arguments = swapon_arguments;
            discard_arguments.insert(discard_arguments.begin() + 1, "--discard=pages");
            discard_arguments.push_back(mapped.string());
            if (run_command(discard_arguments) != 0) {
                std::cerr << "swapzctl: swapon page-discard unavailable; retrying without it\n";
                swapon_arguments.push_back(mapped.string());
                require_success(swapon_arguments, "swapon fallback");
            }
        } else {
            swapon_arguments.push_back(mapped.string());
            require_success(swapon_arguments, "swapon");
        }
    } catch (...) {
        run_command({"swapoff", mapped.string()});
        run_command({"dmsetup", "remove", options.name});
        throw;
    }

    std::cout << "swapzctl: " << mapped << " active: logical=" << logical_bytes
              << " physical=" << physical_bytes << " priority=" << options.priority << '\n';
}

void stop(std::string_view name) {
    if (geteuid() != 0) fail("stop requires root");
    const auto mapped = mapper_path(name);
    const int swapoff_result = run_command({"swapoff", mapped.string()});
    if (swapoff_result != 0 && std::filesystem::exists(mapped)) {
        fail("swapoff failed with status " + std::to_string(swapoff_result));
    }
    require_success({"dmsetup", "remove", std::string(name)}, "removing swapz mapping");
}

void status(std::string_view name) {
    require_success({"dmsetup", "status", std::string(name)}, "dmsetup status");
}

void usage() {
    std::cerr <<
        "Usage:\n"
        "  swapzctl start <block-device> [--size 4G] [--name swapz0] [--priority 100] [--no-discard]\n"
        "  swapzctl stop [name]\n"
        "  swapzctl status [name]\n";
}

} // namespace

int main(int argc, char **argv) {
    try {
        if (argc < 2) { usage(); return 2; }
        const std::string_view command = argv[1];
        if (command == "start") {
            if (argc < 3) { usage(); return 2; }
            StartOptions options;
            options.backing = argv[2];
            for (int index = 3; index < argc; ++index) {
                const std::string_view argument = argv[index];
                if (argument == "--size" && index + 1 < argc) options.logical_bytes = parse_size(argv[++index]);
                else if (argument == "--name" && index + 1 < argc) options.name = argv[++index];
                else if (argument == "--priority" && index + 1 < argc) {
                    const std::string_view value = argv[++index];
                    const auto [end, error] = std::from_chars(value.data(), value.data() + value.size(), options.priority);
                    if (error != std::errc{} || end != value.data() + value.size()) fail("invalid priority");
                } else if (argument == "--no-discard") options.upper_discard = false;
                else fail("unknown start option: " + std::string(argument));
            }
            start(options);
            return 0;
        }
        if (command == "stop") {
            stop(argc >= 3 ? std::string_view(argv[2]) : std::string_view("swapz0"));
            return 0;
        }
        if (command == "status") {
            status(argc >= 3 ? std::string_view(argv[2]) : std::string_view("swapz0"));
            return 0;
        }
        usage();
        return 2;
    } catch (const std::exception &error) {
        std::cerr << "swapzctl: " << error.what() << '\n';
        return 1;
    }
}
