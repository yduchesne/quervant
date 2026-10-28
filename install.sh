#!/usr/bin/env bash
# install.sh — idempotent dependency installer for the Quervant repository.
#
# Installs:
#   1. OS packages needed to build and profile Quervant (git/curl/compiler,
#      perf and heaptrack) using the host package manager and sudo/root.
#   2. The Rust toolchains and components used by this repository
#      (stable + 1.85.0 MSRV, rustfmt, clippy, llvm-tools-preview) as an
#      ordinary user, never as root.
#   3. Cargo tools used by the mandatory local gates and profiling wrappers
#      (cargo-llvm-cov, cargo-flamegraph), also as an ordinary user.
#
# The script is safe to re-run: it queries what is already present and installs
# only what is missing. It never edits shell profiles; if rustup is installed by
# this script, it prints the PATH line to add for the target user.
#
# Root behavior:
#   sudo ./install.sh -y          # OS packages as root; Rust tools as $SUDO_USER
#   ./install.sh -y               # OS packages via sudo; Rust tools as you
#   sudo ./install.sh -y --user alice
#                                 # OS packages as root; Rust tools as alice
#   The script refuses to install Rust/Cargo tooling as root and refuses to
#   guess when no ordinary invoking user is available.
#
# Testing without root: use --mock. Mock mode prints the exact commands and
# simulates installed state in an installer-owned state directory. It never
# invokes sudo, the package manager, rustup or cargo. --reset-mock only removes
# a directory that contains this installer's ownership marker.
#
# Usage:
#   ./install.sh [--mock] [--pm apt|dnf|yum|pacman|zypper|apk]
#                [--os-id ubuntu|debian|fedora|...]
#                [--user USER]
#                [--mock-state DIR] [--reset-mock]
#                [--skip-os] [--skip-rust] [--skip-tools]
#                [--without-flamegraph] [-y|--yes]
#
# Examples:
#   ./install.sh --mock --reset-mock                 # inspect the real plan
#   ./install.sh --mock --pm dnf --os-id fedora      # inspect RPM mapping
#   sudo ./install.sh -y                             # real install
#   ./install.sh -y                                  # real install via sudo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCK=0
PM_OVERRIDE=""
OS_ID_OVERRIDE=""
TARGET_USER_OVERRIDE=""
RESET_MOCK=0
SKIP_OS=0
SKIP_RUST=0
SKIP_TOOLS=0
WITH_FLAMEGRAPH=1
MOCK_STATE_DIR="${QUERVANT_INSTALL_MOCK_STATE:-${TMPDIR:-/tmp}/quervant-install-mock-${UID}}"
MOCK_MARKER_NAME=".quervant-install-mock-owner"
MOCK_MARKER_VALUE="quervant-install-mock-state-v1:${UID}"

ROOT_SUDO=()
TARGET_USER=""
TARGET_UID=""
TARGET_HOME=""
CARGO_BIN_DIR=""

log() { printf '[install] %s\n' "$*"; }
warn() { printf '[install] warning: %s\n' "$*" >&2; }
die() { printf '[install] error: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
install.sh — idempotent dependency installer for the Quervant repository.

OS packages are installed with sudo/root. Rustup, Rust toolchains/components
and Cargo tools are installed as an ordinary user, never as root.

Usage:
  ./install.sh [--mock] [--pm apt|dnf|yum|pacman|zypper|apk]
               [--os-id ubuntu|debian|fedora|...]
               [--user USER]
               [--mock-state DIR] [--reset-mock]
               [--skip-os] [--skip-rust] [--skip-tools]
               [--without-flamegraph] [-y|--yes]

Options:
  --mock                Print the plan and simulate state; never execute installs.
  --pm NAME             Override detected package manager.
  --os-id ID            Override detected distro ID (affects apt package names).
  --user USER           Install Rust/Cargo tooling as USER. Defaults to the
                        invoking user ($SUDO_USER when run via sudo).
  --mock-state DIR      Mock state directory (must be empty, missing, or owned
                        by this installer).
  --reset-mock          Remove an installer-owned mock state directory. Requires
                        --mock and a matching ownership marker.
  --skip-os             Do not install OS packages.
  --skip-rust           Do not install Rustup/toolchains.
  --skip-tools          Do not install cargo-llvm-cov/cargo-flamegraph.
  --without-flamegraph  Do not install cargo-flamegraph.
  -y, --yes             Non-interactive (the default; kept for clarity).

Examples:
  ./install.sh --mock --reset-mock
  ./install.sh --mock --pm dnf --os-id fedora
  sudo ./install.sh -y
  ./install.sh -y
EOF
}

print_cmd() {
    printf '[mock] '
    printf '%q ' "$@"
    printf '\n'
}

normalize_mock_state_dir() {
    [[ -n "$MOCK_STATE_DIR" ]] || die "mock state directory must not be empty"
    while [[ "$MOCK_STATE_DIR" == */ && "$MOCK_STATE_DIR" != "/" ]]; do
        MOCK_STATE_DIR="${MOCK_STATE_DIR%/}"
    done
}

canonical_path() {
    if command -v realpath >/dev/null 2>&1; then
        realpath -m -- "$1"
        return
    fi
    local parent base
    parent="$(dirname -- "$1")"
    base="$(basename -- "$1")"
    (cd -- "$parent" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "$base")
}

mock_marker_path() {
    printf '%s/%s\n' "$MOCK_STATE_DIR" "$MOCK_MARKER_NAME"
}

mock_init() {
    [[ -n "$MOCK_STATE_DIR" ]] || die "mock state directory must not be empty"
    if [[ -L "$MOCK_STATE_DIR" ]]; then
        die "refusing to use a symlinked mock state directory: $MOCK_STATE_DIR"
    fi
    if [[ -e "$MOCK_STATE_DIR" && ! -d "$MOCK_STATE_DIR" ]]; then
        die "mock state path exists and is not a directory: $MOCK_STATE_DIR"
    fi
    if [[ ! -d "$MOCK_STATE_DIR" ]]; then
        mkdir -p -- "$MOCK_STATE_DIR"
    fi
    local marker
    marker="$(mock_marker_path)"
    if [[ -e "$marker" ]]; then
        [[ -f "$marker" && ! -L "$marker" ]] || die "mock ownership marker is not a regular file: $marker"
        [[ "$(cat -- "$marker")" == "$MOCK_MARKER_VALUE" ]] || die \
            "refusing to use mock state with a different ownership marker: $MOCK_STATE_DIR"
        return
    fi
    if [[ -n "$(ls -A -- "$MOCK_STATE_DIR" 2>/dev/null)" ]]; then
        die "refusing to adopt a non-empty directory without an installer ownership marker: $MOCK_STATE_DIR"
    fi
    printf '%s\n' "$MOCK_MARKER_VALUE" >"$marker"
}

mock_reset() {
    [[ -n "$MOCK_STATE_DIR" ]] || die "refusing to reset an empty mock state path"
    if [[ ! -e "$MOCK_STATE_DIR" && ! -L "$MOCK_STATE_DIR" ]]; then
        log "no mock state to reset: $MOCK_STATE_DIR"
        return
    fi
    if [[ -L "$MOCK_STATE_DIR" || ! -d "$MOCK_STATE_DIR" ]]; then
        die "refusing to reset a non-directory or symlinked mock state path: $MOCK_STATE_DIR"
    fi
    local marker
    marker="$(mock_marker_path)"
    if [[ ! -f "$marker" || -L "$marker" ]]; then
        die "refusing to reset: missing installer ownership marker in $MOCK_STATE_DIR"
    fi
    if [[ "$(cat -- "$marker")" != "$MOCK_MARKER_VALUE" ]]; then
        die "refusing to reset: mock ownership marker does not match this installer/user"
    fi

    local real_state real_home real_repo
    real_state="$(canonical_path "$MOCK_STATE_DIR")" || die "cannot canonicalize mock state path"
    real_home="$(canonical_path "$HOME")" || die "cannot canonicalize HOME"
    real_repo="$(canonical_path "$SCRIPT_DIR")" || die "cannot canonicalize repository path"
    [[ "$real_state" != "/" ]] || die "refusing to reset the filesystem root"
    [[ "$real_state" != "$real_home" ]] || die "refusing to reset the home directory"
    case "$real_home/" in
        "$real_state"/*) die "refusing to reset an ancestor of the home directory" ;;
    esac
    case "$real_repo/" in
        "$real_state"/*) die "refusing to reset an ancestor of the repository" ;;
    esac

    rm -rf -- "$MOCK_STATE_DIR"
    log "removed installer-owned mock state: $MOCK_STATE_DIR"
}

mock_file() {
    printf '%s/%s\n' "$MOCK_STATE_DIR" "$1"
}

mock_has() {
    local file entry
    file="$(mock_file "$1")"
    entry="$2"
    [[ -f "$file" ]] && grep -Fxq -- "$entry" "$file"
}

mock_add() {
    local file entry
    file="$(mock_file "$1")"
    entry="$2"
    mkdir -p -- "$MOCK_STATE_DIR"
    touch -- "$file"
    grep -Fxq -- "$entry" "$file" || printf '%s\n' "$entry" >>"$file"
}

run_root() {
    if ((MOCK)); then
        print_cmd "${ROOT_SUDO[@]}" "$@"
    else
        "${ROOT_SUDO[@]}" "$@"
    fi
}

run_user_env() {
    local -a env_args=(
        "HOME=$TARGET_HOME"
        "PATH=$CARGO_BIN_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    )
    if ((MOCK)); then
        print_cmd "as-user=$TARGET_USER" env "${env_args[@]}" "$@"
        return
    fi
    if [[ "$TARGET_USER" == "$(id -un)" ]]; then
        env "${env_args[@]}" "$@"
    else
        sudo -u "$TARGET_USER" -H -- env "${env_args[@]}" "$@"
    fi
}

parse_args() {
    while (($# > 0)); do
        case "$1" in
            --mock) MOCK=1 ;;
            --pm)
                [[ $# -ge 2 ]] || die "--pm requires a value"
                PM_OVERRIDE="$2"
                shift
                ;;
            --os-id)
                [[ $# -ge 2 ]] || die "--os-id requires a value"
                OS_ID_OVERRIDE="$2"
                shift
                ;;
            --user)
                [[ $# -ge 2 ]] || die "--user requires a value"
                TARGET_USER_OVERRIDE="$2"
                shift
                ;;
            --mock-state)
                [[ $# -ge 2 ]] || die "--mock-state requires a directory"
                MOCK_STATE_DIR="$2"
                shift
                ;;
            --reset-mock) RESET_MOCK=1 ;;
            --skip-os) SKIP_OS=1 ;;
            --skip-rust) SKIP_RUST=1 ;;
            --skip-tools) SKIP_TOOLS=1 ;;
            --without-flamegraph) WITH_FLAMEGRAPH=0 ;;
            -y | --yes) : ;; # installation is always non-interactive
            -h | --help)
                usage
                exit 0
                ;;
            *) die "unknown argument: $1 (use --help)" ;;
        esac
        shift
    done

    if ((RESET_MOCK)) && ((MOCK == 0)); then
        die "--reset-mock is only valid with --mock"
    fi
    if [[ -n "$PM_OVERRIDE" ]]; then
        case "$PM_OVERRIDE" in
            apt | dnf | yum | pacman | zypper | apk) ;;
            *) die "unsupported package manager: $PM_OVERRIDE" ;;
        esac
    fi
}

detect_distro() {
    OS_ID="unknown"
    OS_LIKE=""
    if [[ -n "$OS_ID_OVERRIDE" ]]; then
        OS_ID="$OS_ID_OVERRIDE"
        return
    fi
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS_ID="${ID:-unknown}"
        OS_LIKE="${ID_LIKE:-}"
    fi
}

detect_pm() {
    if [[ -n "$PM_OVERRIDE" ]]; then
        PM="$PM_OVERRIDE"
    else
        PM=""
        local candidate
        for candidate in apt-get dnf yum pacman zypper apk; do
            if command -v "$candidate" >/dev/null 2>&1; then
                case "$candidate" in
                    apt-get) PM=apt ;;
                    *) PM="$candidate" ;;
                esac
                break
            fi
        done
    fi
    if [[ -z "$PM" ]]; then
        if ((MOCK)); then
            PM=apt
            warn "no package manager detected; mock mode defaults to apt (use --pm to override)"
        else
            die "no supported package manager found (apt, dnf, yum, pacman, zypper, apk)"
        fi
    fi
}

setup_privilege() {
    if [[ "$(id -u)" -eq 0 ]]; then
        ROOT_SUDO=()
        return
    fi
    command -v sudo >/dev/null 2>&1 || die "sudo is required for OS package installation"
    ROOT_SUDO=(sudo)
}

setup_target_user() {
    if [[ -n "$TARGET_USER_OVERRIDE" ]]; then
        TARGET_USER="$TARGET_USER_OVERRIDE"
    elif [[ "$(id -u)" -ne 0 ]]; then
        TARGET_USER="$(id -un)"
    elif [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        TARGET_USER="$SUDO_USER"
    else
        die "refusing to install Rust tooling as root; run as the developer user (OS packages will use sudo) or pass --user USER"
    fi
    if [[ "$TARGET_USER" == "root" ]]; then
        die "refusing to install Rust tooling as root; pass --user USER or run without sudo"
    fi
    TARGET_UID="$(id -u "$TARGET_USER" 2>/dev/null)" || die "unknown user: $TARGET_USER"
    TARGET_HOME="$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6)"
    if [[ -z "$TARGET_HOME" ]]; then
        TARGET_HOME="$(awk -F: -v user="$TARGET_USER" '$1 == user { print $6; exit }' /etc/passwd)"
    fi
    if [[ -z "$TARGET_HOME" || ! -d "$TARGET_HOME" ]]; then
        die "cannot resolve a real home directory for user $TARGET_USER"
    fi
    CARGO_BIN_DIR="$TARGET_HOME/.cargo/bin"
    if [[ "$TARGET_USER" != "$(id -un)" ]]; then
        command -v sudo >/dev/null 2>&1 || die "sudo is required to run Rust tooling as $TARGET_USER"
    fi
}

os_package_list() {
    case "$PM" in
        apt)
            printf '%s\n' ca-certificates curl git build-essential pkg-config
            if [[ "$OS_ID" == "ubuntu" || " $OS_LIKE " == *" ubuntu "* || "$OS_ID" == "unknown" ]]; then
                # Ubuntu-family perf packages (the operator-prescribed set).
                printf '%s\n' linux-tools-common linux-tools-generic
            else
                # Debian and other apt-based distributions.
                printf '%s\n' linux-perf
            fi
            printf '%s\n' heaptrack
            ;;
        dnf | yum)
            printf '%s\n' ca-certificates curl git gcc gcc-c++ make perf heaptrack
            ;;
        pacman)
            printf '%s\n' ca-certificates curl git base-devel perf heaptrack
            ;;
        zypper)
            printf '%s\n' ca-certificates curl git gcc gcc-c++ make perf heaptrack
            ;;
        apk)
            printf '%s\n' ca-certificates curl git build-base perf heaptrack
            ;;
        *)
            die "unsupported package manager: $PM"
            ;;
    esac
}

pkg_installed() {
    local pkg="$1"
    if ((MOCK)); then
        mock_has packages "$pkg"
        return
    fi
    case "$PM" in
        apt)
            dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'install ok installed'
            ;;
        dnf | yum | zypper)
            rpm -q "$pkg" >/dev/null 2>&1
            ;;
        pacman)
            pacman -Q "$pkg" >/dev/null 2>&1
            ;;
        apk)
            apk info -e "$pkg" >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}

pkg_install() {
    case "$PM" in
        apt) run_root apt-get install -y "$@" ;;
        dnf) run_root dnf install -y "$@" ;;
        yum) run_root yum install -y "$@" ;;
        pacman) run_root pacman -S --needed --noconfirm "$@" ;;
        zypper) run_root zypper --non-interactive install "$@" ;;
        apk) run_root apk add --no-cache "$@" ;;
    esac
}

install_os_packages() {
    if ((SKIP_OS)); then
        log "skipping OS packages (--skip-os)"
        return
    fi
    local -a packages=()
    mapfile -t packages < <(os_package_list)
    local -a missing=()
    local pkg
    for pkg in "${packages[@]}"; do
        if ! pkg_installed "$pkg"; then
            missing+=("$pkg")
        fi
    done
    if ((${#missing[@]} == 0)); then
        log "OS packages already present for $PM ($OS_ID)"
        return
    fi
    log "installing OS packages for $PM ($OS_ID): ${missing[*]}"
    if [[ "$PM" == "apt" ]]; then
        run_root apt-get update -qq
    fi
    pkg_install "${missing[@]}"
    if ((MOCK)); then
        for pkg in "${missing[@]}"; do
            mock_add packages "$pkg"
        done
    fi
}

rustup_toolchain_installed() {
    local tc="$1"
    if ((MOCK)); then
        mock_has toolchains "$tc"
        return
    fi
    run_user_env "$RUSTUP_CMD" toolchain list 2>/dev/null | awk '{print $1}' | grep -Eq "^${tc}(-|$)"
}

rustup_component_installed() {
    local tc="$1"
    local component="$2"
    local installed_name="$component"
    if [[ "$component" == "llvm-tools-preview" ]]; then
        installed_name="llvm-tools"
    fi
    if ((MOCK)); then
        mock_has "components-$tc" "$component"
        return
    fi
    run_user_env "$RUSTUP_CMD" component list --installed --toolchain "$tc" 2>/dev/null \
        | grep -Eq "^${installed_name}(-|$)"
}

rustup_toolchain_install() {
    local tc="$1"
    shift
    local -a components=("$@")
    local -a missing=()
    local component
    if rustup_toolchain_installed "$tc"; then
        for component in "${components[@]}"; do
            if ! rustup_component_installed "$tc" "$component"; then
                missing+=("$component")
            fi
        done
        if ((${#missing[@]} == 0)); then
            log "Rust toolchain $tc and components already present for $TARGET_USER"
            return
        fi
        log "adding missing components for $tc as $TARGET_USER: ${missing[*]}"
        run_user_env "$RUSTUP_CMD" component add --toolchain "$tc" "${missing[@]}"
    else
        log "installing Rust toolchain $tc as $TARGET_USER with components: ${components[*]}"
        local joined
        joined=$(IFS=,; printf '%s' "${components[*]}")
        run_user_env "$RUSTUP_CMD" toolchain install "$tc" --profile minimal --component "$joined"
        missing=("${components[@]}")
    fi
    if ((MOCK)); then
        mock_add toolchains "$tc"
        for component in "${missing[@]}"; do
            mock_add "components-$tc" "$component"
        done
    fi
}

install_rustup() {
    if ((MOCK)); then
        RUSTUP_CMD=rustup
        CARGO_CMD=cargo
        if [[ -f "$(mock_file rustup)" ]]; then
            log "rustup already present for $TARGET_USER (mock)"
            return
        fi
        log "installing rustup as $TARGET_USER (mock)"
        print_cmd curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
            -o "$MOCK_STATE_DIR/rustup-init.sh"
        print_cmd "as-user=$TARGET_USER" sh "$MOCK_STATE_DIR/rustup-init.sh" \
            -y --profile minimal --no-modify-path
        mock_add rustup rustup
        return
    fi

    if [[ -x "$CARGO_BIN_DIR/rustup" ]]; then
        RUSTUP_CMD="$CARGO_BIN_DIR/rustup"
        [[ -x "$CARGO_BIN_DIR/cargo" ]] || die "rustup exists for $TARGET_USER but cargo is missing"
        CARGO_CMD="$CARGO_BIN_DIR/cargo"
        log "rustup already present for $TARGET_USER: $RUSTUP_CMD"
        return
    fi
    if run_user_env sh -c 'command -v rustup >/dev/null 2>&1'; then
        RUSTUP_CMD=rustup
        if ! run_user_env sh -c 'command -v cargo >/dev/null 2>&1'; then
            die "rustup is present for $TARGET_USER but cargo is not on that user's PATH"
        fi
        CARGO_CMD=cargo
        log "rustup already present for $TARGET_USER"
        return
    fi

    command -v curl >/dev/null 2>&1 || die "curl is required to install rustup"
    local tmp rc
    tmp="$(mktemp "${TMPDIR:-/tmp}/quervant-rustup-init.XXXXXX")"
    log "downloading rustup-init"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o "$tmp"
    chmod 0644 -- "$tmp"
    log "installing rustup as $TARGET_USER (minimal profile, no shell-profile edits)"
    set +e
    run_user_env sh "$tmp" -y --profile minimal --no-modify-path
    rc=$?
    set -e
    rm -f -- "$tmp"
    if [[ "$rc" -ne 0 ]]; then
        die "rustup installation failed as $TARGET_USER (exit $rc)"
    fi
    RUSTUP_CMD="$CARGO_BIN_DIR/rustup"
    CARGO_CMD="$CARGO_BIN_DIR/cargo"
    [[ -x "$RUSTUP_CMD" ]] || die "rustup was not installed at $RUSTUP_CMD"
    [[ -x "$CARGO_CMD" ]] || die "cargo was not installed at $CARGO_CMD"
}

install_rust() {
    if ((SKIP_RUST)); then
        log "skipping Rust toolchains (--skip-rust)"
        return
    fi
    install_rustup
    rustup_toolchain_install stable rustfmt clippy llvm-tools-preview
    rustup_toolchain_install 1.85.0 rustfmt clippy

    if ((MOCK)); then
        if [[ -f "$(mock_file default)" ]]; then
            log "rustup default already set for $TARGET_USER (mock)"
        else
            log "setting rustup default to stable as $TARGET_USER (mock)"
            print_cmd "as-user=$TARGET_USER" rustup default stable
            printf 'stable\n' >"$(mock_file default)"
        fi
    elif ! run_user_env "$RUSTUP_CMD" default 2>/dev/null | grep -q '(default)'; then
        log "setting rustup default to stable for $TARGET_USER"
        run_user_env "$RUSTUP_CMD" default stable
    else
        log "rustup default already set for $TARGET_USER"
    fi
}

cargo_tool_installed() {
    local binary="$1"
    if ((MOCK)); then
        mock_has cargo-tools "$binary"
        return
    fi
    run_user_env sh -c 'command -v "$1" >/dev/null 2>&1' sh "$binary"
}

install_cargo_tool() {
    local binary="$1"
    local crate="$2"
    if cargo_tool_installed "$binary"; then
        log "cargo tool $binary already present for $TARGET_USER"
        return
    fi
    log "installing cargo tool $binary ($crate) as $TARGET_USER"
    run_user_env "$CARGO_CMD" install "$crate" --locked
    if ((MOCK)); then
        mock_add cargo-tools "$binary"
    fi
}

install_cargo_tools() {
    if ((SKIP_TOOLS)); then
        log "skipping cargo tools (--skip-tools)"
        return
    fi
    if ((SKIP_RUST)); then
        if ((MOCK)); then
            CARGO_CMD="${CARGO_CMD:-cargo}"
        elif ! run_user_env sh -c 'command -v cargo >/dev/null 2>&1'; then
            warn "cargo is unavailable for $TARGET_USER; skipping cargo tools"
            return
        else
            CARGO_CMD=cargo
        fi
    fi
    install_cargo_tool cargo-llvm-cov cargo-llvm-cov
    if ((WITH_FLAMEGRAPH)); then
        install_cargo_tool cargo-flamegraph flamegraph
    else
        log "skipping cargo-flamegraph (--without-flamegraph)"
    fi
}

main() {
    parse_args "$@"
    normalize_mock_state_dir
    if ((RESET_MOCK)); then
        mock_reset
    fi
    if ((MOCK)); then
        mock_init
        log "mock mode; state directory: $MOCK_STATE_DIR"
    fi

    detect_distro
    detect_pm
    if ((SKIP_OS)); then
        ROOT_SUDO=()
    else
        setup_privilege
    fi
    if ((SKIP_RUST == 0 || SKIP_TOOLS == 0)); then
        setup_target_user
    fi

    if [[ -n "$TARGET_USER" ]]; then
        log "host: os=$OS_ID like=${OS_LIKE:-none} package_manager=$PM rust_user=$TARGET_USER"
    else
        log "host: os=$OS_ID like=${OS_LIKE:-none} package_manager=$PM"
    fi
    install_os_packages
    install_rust
    install_cargo_tools

    if ((MOCK)); then
        log "mock run complete; no real packages, toolchains or cargo tools were changed"
    else
        log "install complete"
    fi
    if [[ -n "$CARGO_BIN_DIR" ]]; then
        log "Rust/Cargo tools were installed for $TARGET_USER; ensure this is on that user's PATH:"
        log "  export PATH=\"$CARGO_BIN_DIR:\$PATH\""
    fi
    if [[ "$PM" == "yum" || "$OS_ID" == "rhel" || "$OS_ID" == "centos" || "$OS_ID" == "rocky" || "$OS_ID" == "almalinux" ]]; then
        warn "heaptrack may require the EPEL repository on RHEL-family systems"
    fi
    if [[ "$PM" == "apk" ]]; then
        warn "heaptrack may need the Alpine community repository"
    fi
}

main "$@"
