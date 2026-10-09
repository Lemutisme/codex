/* Future-only Linux submission build/runtime prototype, NOT an exploration sandbox.
 * Build: cc -std=c11 -O2 -Wall -Wextra -Werror -static -o launcher this_file.c
 * Trusted caller supplies the grants and immutable inputs; this does not authenticate
 * a policy, freeze other processes, prove Rust authorship, or identify reference reuse.
 * --candidate registers a read-only entrypoint (including a build script), not provenance.
 * Content writes/truncation are denied outside scratch; chmod/utime metadata is not
 * mediated by Landlock. Separate ownership/read-only mounts must supply that isolation.
 * Every explicit file grant is one regular inode; --list grants directory NAMES only.
 * Fixed, verified /dev/null is also readable/writable for ordinary subprocess stdio. Scratch
 * never receives EXECUTE. Interpreters may compute arbitrary code from permitted data.
 * TCP/UDP remain possible: network isolation belongs to the caller. AF_UNIX/FD-broker,
 * anonymous-executable and io_uring profiles are deliberately unsupported. Stdio is
 * pipes or /dev/null; --pty-stdio also accepts caller-owned devpts slaves. The caller
 * must dedicate those PTYs, not lend its interactive terminal. No /dev/tty/openpty
 * broker or complete terminal/environment compatibility is claimed. Only stdio survives.
 * A normal PATH enables granted tool-name lookup; --path/--term are explicit caller data,
 * never inherited secrets. Neither can widen the kernel's file permissions.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <linux/audit.h>
#include <linux/capability.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/magic.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/vfs.h>
#include <unistd.h>
#include <fcntl.h>

#if defined(__x86_64__) && !defined(__ILP32__)
#define NATIVE_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define NATIVE_ARCH AUDIT_ARCH_AARCH64
#else
#error "Only native Linux x86_64 and aarch64 are supported"
#endif
#define MAX_GRANTS 4096
#define FS_READ LANDLOCK_ACCESS_FS_READ_FILE
#define FS_EXEC LANDLOCK_ACCESS_FS_EXECUTE
#define FS_LIST LANDLOCK_ACCESS_FS_READ_DIR
#define FS_ALL ((UINT64_C(1) << 15) - 1) /* ABI 3, including REFER and TRUNCATE. */
#define DENY(nr) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (nr), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)

struct grant { const char *kind; const char *path; };

static void fail(const char *message) {
    fprintf(stderr, "capability launcher: %s (%s)\n", message, strerror(errno));
    exit(125);
}

static int open_canonical(const char *path, int directory) {
    char resolved[PATH_MAX];
    struct stat info;
    if (path[0] != '/' || !realpath(path, resolved) || strcmp(path, resolved))
        fail("grants must use canonical absolute paths");
    int fd = open(path, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0 || fstat(fd, &info)) fail("cannot open grant");
    if (directory ? !S_ISDIR(info.st_mode) :
        (!S_ISREG(info.st_mode) || info.st_nlink != 1))
        fail("grant must be a directory or independent regular file");
    struct statfs fs;
    if (fstatfs(fd, &fs)) fail("cannot inspect grant filesystem");
    if (fs.f_type == PROC_SUPER_MAGIC || fs.f_type == SYSFS_MAGIC ||
        fs.f_type == DEVPTS_SUPER_MAGIC || fs.f_type == DEBUGFS_MAGIC ||
        fs.f_type == TRACEFS_MAGIC || fs.f_type == SECURITYFS_MAGIC ||
        fs.f_type == BPF_FS_MAGIC) fail("virtual filesystem grants are unsupported");
    return fd;
}

static void add_rule(int ruleset, int fd, uint64_t access) {
    struct landlock_path_beneath_attr rule = {
        .allowed_access = access, .parent_fd = fd
    };
    if (syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH,
                &rule, 0)) fail("cannot install Landlock rule");
}

static void restrict_descriptor_import(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, NATIVE_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Reject x32 and invalid high syscall numbers, not just the audit arch. */
        BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, 0x40000000, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        DENY(SYS_memfd_create), DENY(SYS_pidfd_getfd),
        DENY(SYS_open_by_handle_at), DENY(SYS_execveat),
        DENY(SYS_io_uring_setup), DENY(SYS_io_uring_enter),
        DENY(SYS_io_uring_register), DENY(SYS_socketpair),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_ioctl, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, TIOCSTI, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* A socket returned to this domain can never carry SCM_RIGHTS. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_socket, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_UNIX, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = filter
    };
    if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program))
        fail("cannot install inherited descriptor filter");
}

int main(int argc, char **argv) {
    struct grant grants[MAX_GRANTS];
    const char *scratch = NULL, *candidate = NULL;
    const char *search_path = "/usr/bin:/bin", *terminal = NULL;
    size_t count = 0;
    int command = 0, pty_stdio = 0, path_override = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--")) { command = i + 1; break; }
        if (!strcmp(argv[i], "--pty-stdio")) {
            if (pty_stdio) fail("duplicate PTY capability");
            pty_stdio = 1;
            continue;
        }
        if (i + 1 >= argc) fail("missing grant argument");
        const char *kind = argv[i], *path = argv[++i];
        if (!strcmp(kind, "--scratch")) {
            if (scratch) fail("duplicate scratch");
            scratch = path;
        } else if (!strcmp(kind, "--path")) {
            if (path_override || !*path || strlen(path) > 4096)
                fail("require one bounded explicit PATH");
            path_override = 1;
            search_path = path;
        } else if (!strcmp(kind, "--term")) {
            if (terminal || !*path || strlen(path) > 128 ||
                strspn(path, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._+-") != strlen(path))
                fail("require one bounded terminal name");
            terminal = path;
        } else if (!strcmp(kind, "--exec") || !strcmp(kind, "--read") ||
                   !strcmp(kind, "--list") || !strcmp(kind, "--candidate")) {
            if (count == MAX_GRANTS) fail("too many grants");
            if (!strcmp(kind, "--candidate")) {
                if (candidate) fail("duplicate candidate");
                candidate = path;
            }
            grants[count++] = (struct grant){kind, path};
        } else fail("unknown option");
    }
    if (!scratch || !candidate || !command || command >= argc)
        fail("require --scratch DIR --candidate FILE [--exec/--read FILE] [--list DIR] -- COMMAND [ARGS]");
    if (getuid() != geteuid() || getgid() != getegid() || geteuid() == 0)
        fail("privileged launcher profiles are unsupported");
    struct __user_cap_header_struct cap_header = {
        .version = _LINUX_CAPABILITY_VERSION_3, .pid = 0
    };
    struct __user_cap_data_struct capabilities[2];
    if (syscall(SYS_capget, &cap_header, capabilities)) fail("cannot inspect capabilities");
    for (size_t i = 0; i < 2; i++)
        if (capabilities[i].effective || capabilities[i].permitted || capabilities[i].inheritable)
            fail("capability-bearing launcher profiles are unsupported");
    for (int fd = 0; fd < 3; fd++) {
        struct stat info;
        struct statfs fs;
        unsigned int number;
        if (fstat(fd, &info)) fail("cannot inspect stdio");
        int permitted = S_ISFIFO(info.st_mode) ||
            (S_ISCHR(info.st_mode) && info.st_rdev == makedev(1, 3));
        if (!permitted && pty_stdio && S_ISCHR(info.st_mode) &&
            info.st_uid == geteuid() && !fstatfs(fd, &fs) &&
            fs.f_type == DEVPTS_SUPER_MAGIC && isatty(fd)) {
            errno = 0;
            permitted = ioctl(fd, TIOCGPTN, &number) < 0 && errno == ENOTTY;
        }
        if (!permitted) fail("stdio requires pipes, /dev/null or explicit dedicated PTY slaves");
    }
    int abi = syscall(SYS_landlock_create_ruleset, NULL, 0,
                      LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 3) fail("Landlock ABI 3 or newer is required; no fallback");
    int scratch_fd = open_canonical(scratch, 1);
    struct stat scratch_info;
    if (fstat(scratch_fd, &scratch_info) || scratch_info.st_uid != geteuid() ||
        (scratch_info.st_mode & 0777) != 0700) fail("scratch must be owned mode 0700");
    int scan_fd = openat(scratch_fd, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    DIR *directory = scan_fd < 0 ? NULL : fdopendir(scan_fd);
    if (!directory) fail("cannot inspect scratch");
    struct dirent *entry;
    errno = 0;
    while ((entry = readdir(directory)))
        if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, ".."))
            fail("scratch must be empty");
    if (errno) fail("cannot enumerate scratch");
    closedir(directory);
    struct landlock_ruleset_attr rules = {.handled_access_fs = FS_ALL};
    int ruleset = syscall(SYS_landlock_create_ruleset, &rules, sizeof(rules), 0);
    if (ruleset < 0) fail("cannot create Landlock ruleset");
    int null_fd = open("/dev/null", O_PATH | O_NOFOLLOW | O_CLOEXEC);
    struct stat null_info;
    if (null_fd < 0 || fstat(null_fd, &null_info) ||
        !S_ISCHR(null_info.st_mode) || null_info.st_rdev != makedev(1, 3))
        fail("/dev/null must be the standard null device");
    add_rule(ruleset, null_fd, FS_READ | LANDLOCK_ACCESS_FS_WRITE_FILE);
    close(null_fd);
    int initial_allowed = 0;
    size_t prefix = strlen(scratch);
    for (size_t i = 0; i < count; i++) {
        const char *path = grants[i].path, *kind = grants[i].kind;
        int listing = !strcmp(kind, "--list");
        int executable = !strcmp(kind, "--exec") || !strcmp(kind, "--candidate");
        if (!strncmp(path, scratch, prefix) &&
            (path[prefix] == '/' || path[prefix] == '\0'))
            fail("immutable grants cannot be inside writable scratch");
        int fd = open_canonical(path, listing);
        struct stat info;
        if (fstat(fd, &info)) fail("cannot inspect grant");
        if (executable && !(info.st_mode & 0111)) fail("executable grant lacks mode");
        if (!strcmp(kind, "--candidate") && (info.st_mode & 0222))
            fail("registered candidate must be read-only before launch");
        if (executable && !strcmp(path, argv[command])) initial_allowed = 1;
        add_rule(ruleset, fd, listing ? FS_LIST : FS_READ | (executable ? FS_EXEC : 0));
        close(fd);
    }
    if (!initial_allowed) fail("initial command is not an executable grant");
    /* No REFER: immutable inputs cannot be linked/renamed into a writable domain. */
    uint64_t writable = FS_READ | FS_LIST | LANDLOCK_ACCESS_FS_WRITE_FILE |
        LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_SYM;
    add_rule(ruleset, scratch_fd, writable);
    if (fchdir(scratch_fd)) fail("cannot enter scratch");
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(SYS_landlock_restrict_self, ruleset, 0)) fail("cannot enter Landlock");
    if (syscall(SYS_close_range, 3U, ~0U, 0)) fail("cannot close inherited descriptors");
    restrict_descriptor_import();
    if (clearenv() || setenv("PATH", search_path, 1) ||
        setenv("LANG", "C", 1) || setenv("TMPDIR", scratch, 1) ||
        (terminal && setenv("TERM", terminal, 1)))
        fail("cannot construct child environment");
    execv(argv[command], &argv[command]);
    fail("granted command could not execute");
}
