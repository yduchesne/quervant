#!/usr/bin/env bash
# install.sh — idempotent dependency installer for the Quervant repository.
#
# Installs:
#   1. OS packages needed to build and profile Quervant (git/curl/compiler,
#      perf and heaptrack) using the host package manager.
#   2. The Rust toolchains and components used by this repository
#      (stable + 1.85.0 MSRV, rustfmt, clippy, llvm-tools-preview).
#   3. Cargo tools used by the mandatory local gates and profiling wrappers
#      (cargo-llvm-cov, cargo-flamegraph).
#
# The script is safe to re-run: it queries what is already present and installs
# only what is missing. It never edits shell profiles; if rustup is installed by
# this script, it prints the PATH line to add.
#
# Testing without root: use --mock. Mock mode prints the exact commands and
# simulates installed state in a state directory, so a second --mock run is
# idempotent. It never invokes sudo, the package manager, rustup or cargo.
#
# Usage:
#   ./install.sh [--mock] [--pm apt|dnf|yum|pacman|zypper|apk]
#                [--os-id ubuntu|debian|fedora|...]
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

MOCK=0
PM_OVERRIDE=""
OS_ID_OVERRIDE=""
RESET_MOCK=0
SKIP_OS=0
SKIP_RUST=0
SKIP_TOOLS=0
WITH_FLAMEGRAPH=1
MOCK_STATE_DIR="${QUERVANT_INSTALL_MOCK_STATE:-${TMPDIR:-/tmp}/quervant-install-mock-${UID}}"
PATH_ADDED=0

log() { printf '[install] %s\n' "$*"; }
warn() { printf '[install] warning: %s\n' "$*" >&2; }
die() { printf '[install] error: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

print_cmd() {
    printf '[mock] '
    printf '%q ' "$@"
    printf '\n'
}

run_root() {
    if ((MOCK)); then
        print_cmd "${SUDO[@]}" "$@"
    else
        "${SUDO[@]}" "$@"
    fi
}

run_user() {
    if ((MOCK)); then
        print_cmd "$@"
    else
        "$@"
    fi
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
    mkdir -p "$MOCK_STATE_DIR"
    touch "$file"
    grep -Fxq -- "$entry" "$file" || printf '%s\n' "$entry" >>"$file"
}

mock_reset() {
    [[ -n "$MOCK_STATE_DIR" ]] || die "refusing to reset an empty mock state path"
    case "$MOCK_STATE_DIR" in
        / | "$HOME") die "refusing to reset unsafe mock state path: $MOCK_STATE_DIR" ;;
    esac
    rm -rf -- "$MOCK_STATE_DIR"
    log "removed mock state: $MOCK_STATE_DIR"
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
    if ((MOCK)); then
        SUDO=(sudo)
        return
    fi
    if [[ "$(id -u)" -eq 0 ]]; then
        SUDO=()
        return
    fi
    command -v sudo >/dev/null 2>&1 || die "root is required and sudo is not installed"
    SUDO=(sudo)
}

ensure_cargo_path() {
    if [[ -d "$HOME/.cargo/bin" ]]; then
        case ":$PATH:" in
            *":$HOME/.cargo/bin:"*) ;;
            *)
                export PATH="$HOME/.cargo/bin:$PATH"
                PATH_ADDED=1
                ;;
        esac
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
    "$RUSTUP_CMD" toolchain list 2>/dev/null | awk '{print $1}' | grep -Eq "^${tc}(-|$)"
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
    "$RUSTUP_CMD" component list --installed --toolchain "$tc" 2>/dev/null \
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
            log "Rust toolchain $tc and components already present"
            return
        fi
        log "adding missing components for $tc: ${missing[*]}"
        run_user "$RUSTUP_CMD" component add --toolchain "$tc" "${missing[@]}"
    else
        log "installing Rust toolchain $tc with components: ${components[*]}"
        local joined
        joined=$(IFS=,; printf '%s' "${components[*]}")
        run_user "$RUSTUP_CMD" toolchain install "$tc" --profile minimal --component "$joined"
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
            log "rustup already present (mock)"
            return
        fi
        log "installing rustup (mock)"
        print_cmd curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
            -o "$MOCK_STATE_DIR/rustup-init.sh"
        print_cmd sh "$MOCK_STATE_DIR/rustup-init.sh" -y --profile minimal --no-modify-path
        mkdir -p "$MOCK_STATE_DIR"
        touch "$(mock_file rustup)"
        return
    fi

    ensure_cargo_path
    if command -v rustup >/dev/null 2>&1; then
        RUSTUP_CMD="$(command -v rustup)"
        command -v cargo >/dev/null 2>&1 || die "rustup is present but cargo is not on PATH"
        CARGO_CMD="$(command -v cargo)"
    elif [[ -x "$HOME/.cargo/bin/rustup" ]]; then
        export PATH="$HOME/.cargo/bin:$PATH"
        PATH_ADDED=1
        RUSTUP_CMD="$HOME/.cargo/bin/rustup"
        CARGO_CMD="$HOME/.cargo/bin/cargo"
    else
        command -v curl >/dev/null 2>&1 || die "curl is required to install rustup"
        local tmp
        tmp="$(mktemp -d)"
        log "downloading rustup-init"
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o "$tmp/rustup-init.sh"
        log "installing rustup (minimal profile, no shell-profile edits)"
        sh "$tmp/rustup-init.sh" -y --profile minimal --no-modify-path
        rm -rf -- "$tmp"
        export PATH="$HOME/.cargo/bin:$PATH"
        PATH_ADDED=1
        RUSTUP_CMD="$HOME/.cargo/bin/rustup"
        CARGO_CMD="$HOME/.cargo/bin/cargo"
    fi
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
            log "rustup default already set (mock)"
        else
            log "setting rustup default to stable (mock)"
            print_cmd rustup default stable
            mkdir -p "$MOCK_STATE_DIR"
            printf 'stable\n' >"$(mock_file default)"
        fi
    elif ! "$RUSTUP_CMD" default 2>/dev/null | grep -q '(default)'; then
        log "setting rustup default to stable"
        run_user "$RUSTUP_CMD" default stable
    else
        log "rustup default already set"
    fi
}

cargo_tool_installed() {
    local binary="$1"
    if ((MOCK)); then
        mock_has cargo-tools "$binary"
        return
    fi
    command -v "$binary" >/dev/null 2>&1
}

install_cargo_tool() {
    local binary="$1"
    local crate="$2"
    if cargo_tool_installed "$binary"; then
        log "cargo tool $binary already present"
        return
    fi
    log "installing cargo tool $binary ($crate)"
    run_user "$CARGO_CMD" install "$crate" --locked
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
        elif ! command -v cargo >/dev/null 2>&1; then
            warn "cargo is unavailable; skipping cargo tools"
            return
        else
            CARGO_CMD="$(command -v cargo)"
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
    if ((RESET_MOCK)); then
        mock_reset
    fi
    if ((MOCK)); then
        mkdir -p "$MOCK_STATE_DIR"
        log "mock mode; state directory: $MOCK_STATE_DIR"
    fi

    detect_distro
    detect_pm
    setup_privilege

    log "host: os=$OS_ID like=${OS_LIKE:-none} package_manager=$PM"
    install_os_packages
    install_rust
    install_cargo_tools

    if ((MOCK)); then
        log "mock run complete; no real packages, toolchains or cargo tools were changed"
    else
        log "install complete"
    fi
    if ((PATH_ADDED)); then
        log "add this to your shell profile if cargo/rustup are not found in new shells:"
        log '  export PATH="$HOME/.cargo/bin:$PATH"'
    fi
    if [[ "$PM" == "yum" || "$OS_ID" == "rhel" || "$OS_ID" == "centos" || "$OS_ID" == "rocky" || "$OS_ID" == "almalinux" ]]; then
        warn "heaptrack may require the EPEL repository on RHEL-family systems"
    fi
    if [[ "$PM" == "apk" ]]; then
        warn "heaptrack may need the Alpine community repository"
    fi
}

main "$@"
