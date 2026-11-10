#!/usr/bin/env bash
# Quervant user-systemd maintenance installer.
# Managed units never authorize Podman storage repair/reset or evidence purges.
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: disk-cleanup-schedule.sh --setup [--repo PATH] [--cleanup-script PATH]
       disk-cleanup-schedule.sh --teardown
       disk-cleanup-schedule.sh --help

--setup            Install and enable weekly cleanup and 30-minute disk monitoring.
--teardown         Disable timers and remove only files installed by this script.
--repo PATH        Quervant root (default: Git root of current directory).
--cleanup-script   Existing disk-cleanup.sh (default: REPO/disk-cleanup.sh,
                   then script directory/disk-cleanup.sh).

Schedules: Sunday 03:00 local time (0–30 min randomized delay), and every 30 min.
Monitoring: <70% informational, >=70% warning, >=80% eligible for idle cleanup,
            >=90% critical warning. At most one pressure cleanup every 12 hours.
Safety: never automatically purge benchmark evidence or reset/repair Podman.
        Never run cleanup while a detectable pi coding-agent session or Quervant
        build/benchmark process is active. pi checking covers all user sessions.
        This is process-based best effort, not an atomic interlock with pi.
        A shared flock protects maintenance scripts from each other, but external
        benchmark runners must be stopped or coordinate separately.
EOF
}
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
mode=''; repo=''; source_cleanup=''
while (($#)); do
  case "$1" in
    --setup|--teardown) [[ -z "$mode" ]] || fail 'Specify exactly one of --setup or --teardown'; mode=$1; shift ;;
    --repo|--cleanup-script)
      (($# >= 2)) || fail "$1 requires a path"
      if [[ "$1" == --repo ]]; then repo=$2; else source_cleanup=$2; fi
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done
[[ -n "$mode" ]] || { usage >&2; exit 2; }
if [[ "$mode" == --teardown && ( -n "$repo" || -n "$source_cleanup" ) ]]; then
  fail '--teardown accepts no additional paths'
fi
command -v systemctl >/dev/null || fail 'systemctl not available (requires systemd user manager)'
command -v flock >/dev/null || fail 'flock not available (util-linux required)'
[[ ${EUID:-$(id -u)} -ne 0 ]] || fail 'Run as the regular rootless Podman user, not root/sudo'

unit_dir="$HOME/.config/systemd/user"
install_dir="$HOME/.local/libexec/quervant-maintenance"
state_dir="$HOME/.local/state/quervant-maintenance"
unit_names=(quervant-cleanup.service quervant-cleanup.timer quervant-disk-monitor.service quervant-disk-monitor.timer)
marker='# Managed by disk-cleanup-schedule.sh; do not edit directly.'

check_ownership() {
  local file
  for file in "${unit_names[@]}"; do
    if [[ -e "$unit_dir/$file" ]] && ! grep -Fxq "$marker" "$unit_dir/$file"; then
      fail "Refusing to overwrite unrelated unit: $unit_dir/$file"
    fi
  done
  if [[ -d "$install_dir" ]] && [[ ! -f "$install_dir/.managed-by-disk-cleanup-schedule" ]]; then
    fail "Refusing to modify unknown helper directory: $install_dir"
  fi
}

if [[ "$mode" == --teardown ]]; then
  check_ownership
  for unit in quervant-cleanup.timer quervant-disk-monitor.timer; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
  done
  for unit in quervant-cleanup.service quervant-disk-monitor.service; do
    systemctl --user stop "$unit" 2>/dev/null || true
  done
  for unit in "${unit_names[@]}"; do
    if [[ -f "$unit_dir/$unit" ]] && grep -Fxq "$marker" "$unit_dir/$unit"; then
      rm -f -- "$unit_dir/$unit"
    fi
  done
  if [[ -f "$install_dir/.managed-by-disk-cleanup-schedule" ]]; then
    rm -rf -- "$install_dir"
  fi
  systemctl --user daemon-reload
  printf 'Removed Quervant maintenance timers, units, and managed helpers.\n'
  printf 'Kept state/log history under: %s\n' "$state_dir"
  exit 0
fi

if [[ -z "$repo" ]]; then
  repo=$(git rev-parse --show-toplevel 2>/dev/null) || fail 'Not in a Git worktree; pass --repo PATH'
fi
[[ -d "$repo" ]] || fail "Missing repository: $repo"
repo=$(cd -- "$repo" && pwd -P)
[[ -d "$repo/crates/quervant-core" && -d "$repo/benchmarks/pr15d/adapters/quervant" ]] || fail 'Not a recognized Quervant repository'
if [[ -z "$source_cleanup" ]]; then
  if [[ -f "$repo/disk-cleanup.sh" ]]; then
    source_cleanup="$repo/disk-cleanup.sh"
  else
    source_cleanup="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/disk-cleanup.sh"
  fi
fi
[[ -f "$source_cleanup" && -r "$source_cleanup" ]] || fail "Cleanup script missing: $source_cleanup"
bash -n "$source_cleanup" || fail 'Cleanup script has Bash syntax errors'
systemctl --user show-environment >/dev/null 2>&1 || fail 'systemd user manager unavailable'
check_ownership
mkdir -p -- "$unit_dir" "$install_dir" "$state_dir"
printf 'managed\n' > "$install_dir/.managed-by-disk-cleanup-schedule"
install -m 0755 "$source_cleanup" "$install_dir/disk-cleanup.sh"

# Embed repo as a shell-escaped constant, not an EnvironmentFile needing special quoting.
{
  cat <<'EOF'
#!/usr/bin/env bash
# Managed by disk-cleanup-schedule.sh; do not edit directly.
set -Eeuo pipefail
EOF
  printf 'REPO=%q\n' "$repo"
  cat <<'EOF'
BASE="$HOME/.local/libexec/quervant-maintenance"
STATE="$HOME/.local/state/quervant-maintenance"
mkdir -p "$STATE"
exec 9>"$STATE/maintenance.lock"
# Never wait for another cleanup; overlapping runs are skipped.
flock -n 9 || { echo 'SKIP: another Quervant maintenance run is active'; exit 0; }
# Fail closed when pi-session detection cannot be performed. An active coding-agent
# session can be idle between tool calls yet still need the Cargo target tree.
# Inspect all processes owned by this user, not just processes with Quervant in
# their command line: pi may be launched from a parent directory or another repo.
# The CLI can be an executable named 'pi' or a Node.js cli.js under the
# 'pi-coding-agent' package. Match executable/argument identity, not 'pi' as a
# substring (which would incorrectly match arbitrary commands and filenames).
[[ -d /proc && -r /proc/self/cmdline ]] || {
  echo 'SKIP: cannot inspect /proc for active pi coding-agent sessions' >&2
  exit 0
}
command -v stat >/dev/null 2>&1 || {
  echo 'SKIP: stat is required to verify pi process ownership' >&2
  exit 0
}
check_pi_sessions() {
  local proc pid owner exe arg first value
  local -a argv
  for proc in /proc/[0-9]*; do
    [[ -d "$proc" ]] || continue
    pid=${proc##*/}
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    owner=$(stat -c %u -- "$proc" 2>/dev/null) || continue # exited
    [[ "$owner" == "$(id -u)" ]] || continue
    argv=()
    # Processes can exit between discovery and inspection; distinguish that
    # from an unreadable live process (which blocks destructive cleanup).
    if ! mapfile -d '' -t argv < "$proc/cmdline" 2>/dev/null; then
      [[ -d "$proc" ]] || continue
      echo "SKIP: cannot inspect current-user process $pid for pi" >&2
      return 1
    fi
    ((${#argv[@]})) || continue # zombie/kernel thread
    first=${argv[0]##*/}
    if [[ "$first" == pi ]]; then
      echo "SKIP: active pi session (PID $pid)"
      return 1
    fi
    exe=$(readlink -- "$proc/exe" 2>/dev/null || true)
    if [[ "${exe##*/}" == pi ]]; then
      echo "SKIP: active pi executable (PID $pid)"
      return 1
    fi
    # Node/tsx/npx invocation of the published pi coding-agent CLI.
    for arg in "${argv[@]:1}"; do
      case "$arg" in
        */pi-coding-agent/*|*/pi-coding-agent|*'/@mariozechner/pi-coding-agent/'*|*'/pi-coding-agent/dist/cli.js'*)
          echo "SKIP: active pi coding-agent process (PID $pid)"
          return 1 ;;
      esac
    done
  done
  return 0
}
check_pi_sessions || exit 0
# Detect active Quervant builds/benchmarks by process command lines. The guard is
# deliberately conservative; it cannot guarantee detecting all custom launchers.
if command -v pgrep >/dev/null 2>&1; then
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    # Ignore the wrapper's own PID; match cargo/rustc/benchmark/related adapters.
    pid=${line%% *}
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    cmd=${line#* }
    case "$cmd" in
      *"/quervant/"*|*"/quervant "*|*"quervant-core"*|*"pr15d-quervant-adapter"*)
        if [[ "$cmd" == *cargo* || "$cmd" == *rustc* || "$cmd" == *benchmark* || "$cmd" == *"/benchmarks/"* || "$cmd" == *"pr15d-quervant-adapter"* ]]; then
          echo "SKIP: potential active Quervant workload (PID $pid)"; exit 0
        fi ;;
    esac
  done < <(pgrep -af 'cargo|rustc|benchmarks|quervant-adapter' || true)
fi
# Only regular cleanup; NEVER pass --purge-root-target, repair or reset flags.
"$BASE/disk-cleanup.sh" --repo "$REPO" --apply --yes
EOF
} > "$install_dir/weekly.sh.new"
chmod 0755 "$install_dir/weekly.sh.new"
mv -f -- "$install_dir/weekly.sh.new" "$install_dir/weekly.sh"

{
  cat <<'EOF'
#!/usr/bin/env bash
# Managed by disk-cleanup-schedule.sh; do not edit directly.
set -Eeuo pipefail
EOF
  printf 'REPO=%q\n' "$repo"
  cat <<'EOF'
STATE="$HOME/.local/state/quervant-maintenance"
BASE="$HOME/.local/libexec/quervant-maintenance"
mkdir -p "$STATE"
usage=$(df -P -- "$REPO" | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
[[ "$usage" =~ ^[0-9]+$ && "$usage" -le 100 ]] || { echo "ERROR: unexpected filesystem utilization: $usage" >&2; exit 1; }
if ((usage >= 90)); then
  echo "CRITICAL: Quervant filesystem is ${usage}% full; avoid starting new benchmarks"
elif ((usage >= 80)); then
  echo "WARNING: Quervant filesystem is ${usage}% full; attempting safe idle cleanup"
elif ((usage >= 70)); then
  echo "NOTICE: Quervant filesystem is ${usage}% full"
else
  echo "OK: Quervant filesystem is ${usage}% full"
fi
if ((usage < 80)); then exit 0; fi
# Cooldown avoids repeated automatic cleanup every half-hour on a full disk.
now=$(date +%s)
last=0
if [[ -r "$STATE/pressure-last-attempt" ]]; then
  read -r last < "$STATE/pressure-last-attempt" || last=0
fi
[[ "$last" =~ ^[0-9]+$ ]] || last=0
if ((now - last < 43200 && now >= last)); then
  echo 'SKIP: pressure cleanup attempted in the last 12 hours'; exit 0
fi
# Serialize the cooldown decision itself so monitor runs cannot race.
exec 8>"$STATE/pressure.lock"
flock -n 8 || { echo 'SKIP: pressure monitor already running'; exit 0; }
if [[ -r "$STATE/pressure-last-attempt" ]]; then
  read -r last < "$STATE/pressure-last-attempt" || last=0
fi
[[ "$last" =~ ^[0-9]+$ ]] || last=0
if ((now - last < 43200 && now >= last)); then exit 0; fi
printf '%s\n' "$now" > "$STATE/pressure-last-attempt"
"$BASE/weekly.sh"
EOF
} > "$install_dir/monitor.sh.new"
chmod 0755 "$install_dir/monitor.sh.new"
mv -f -- "$install_dir/monitor.sh.new" "$install_dir/monitor.sh"

cat > "$unit_dir/quervant-cleanup.service" <<EOF
$marker
[Unit]
Description=Quervant safe periodic Cargo/Podman cleanup
[Service]
Type=oneshot
ExecStart=%h/.local/libexec/quervant-maintenance/weekly.sh
EOF
cat > "$unit_dir/quervant-cleanup.timer" <<EOF
$marker
[Unit]
Description=Quervant weekly cleanup timer
[Timer]
OnCalendar=Sun *-*-* 03:00:00
RandomizedDelaySec=30min
Persistent=true
Unit=quervant-cleanup.service
[Install]
WantedBy=timers.target
EOF
cat > "$unit_dir/quervant-disk-monitor.service" <<EOF
$marker
[Unit]
Description=Monitor Quervant disk pressure and safely clean when idle
[Service]
Type=oneshot
ExecStart=%h/.local/libexec/quervant-maintenance/monitor.sh
EOF
cat > "$unit_dir/quervant-disk-monitor.timer" <<EOF
$marker
[Unit]
Description=Monitor Quervant filesystem usage every 30 minutes
[Timer]
OnCalendar=*:0/30
Persistent=true
Unit=quervant-disk-monitor.service
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now quervant-cleanup.timer quervant-disk-monitor.timer
printf '\nInstalled Quervant maintenance for %s\n' "$repo"
printf 'Timers:\n'
systemctl --user list-timers --all quervant-cleanup.timer quervant-disk-monitor.timer || true
printf '\nLogs: journalctl --user -u quervant-cleanup.service -u quervant-disk-monitor.service -n 100\n'
printf 'Remove with: %s --teardown\n' "$0"
