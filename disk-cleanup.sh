#!/usr/bin/env bash
# Quervant benchmark Cargo cleanup plus conservative Podman recovery.
# The ordinary cleanup NEVER authorizes Podman image/volume removal.
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: quervant_cleanup.sh [--repo PATH] [--dry-run | --apply [--yes]]
                           [--allow-podman-repair] [--allow-podman-reset]

  --repo PATH             Quervant repository root (default: current Git root)
  --dry-run               Inventory only (default; no mutations)
  --apply                 Delete recognized benchmark-local Cargo targets and
                          prune stopped Podman containers
  --yes                   Skip normal cleanup prompt; does NOT approve reset
  --allow-podman-repair   If prune fails with a storage-layer error, permit
                          'podman system check --repair' (may delete images)
  --allow-podman-reset    LAST RESORT if storage error persists; REQUIRES a TTY
                          and separate, exact typed confirmation, even with --yes
  -h, --help              Show this help

Safety:
  * Preserves REPO/target/ and all benchmark evidence outside nested Cargo targets.
  * Does not follow symlinked directories, and skips unrecognized targets.
  * Ordinary Podman prune removes only stopped containers.
  * Repair can remove damaged images; reset removes ALL local Podman containers,
    pods, images, networks, volumes and storage for the CURRENT Podman context.
  * Neither repair nor reset runs unless separately opted in.
  * Reset is NEVER automatic; a human must type RESET PODMAN STORAGE at a TTY.
  * Stop Cargo/benchmark jobs and Podman-dependent workloads first; back up
    important Podman-managed volumes before authorizing any reset.
USAGE
}

mode=dry-run
yes=false
allow_repair=false
allow_reset=false
repo=""
while (($#)); do
  case "$1" in
    --repo) (($# >= 2)) || { echo 'Missing argument to --repo' >&2; exit 2; }; repo=$2; shift 2 ;;
    --dry-run) mode=dry-run; shift ;;
    --apply) mode=apply; shift ;;
    --yes) yes=true; shift ;;
    --allow-podman-repair) allow_repair=true; shift ;;
    --allow-podman-reset) allow_reset=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$repo" ]]; then
  repo=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo 'Not inside a Git repository; pass --repo /path/to/quervant' >&2
    exit 2
  }
fi
[[ -d "$repo" ]] || { echo "Repository does not exist: $repo" >&2; exit 2; }
repo=$(cd -- "$repo" && pwd -P)
[[ -d "$repo/benchmarks/pr15d/adapters/quervant" && -d "$repo/crates/quervant-core" ]] || {
  echo "Not a recognized Quervant repository root: $repo" >&2
  exit 2
}
[[ ! -L "$repo/benchmarks" ]] || { echo 'Refusing symlinked benchmarks root' >&2; exit 2; }

is_cargo_target() {
  local d=$1
  [[ -f "$d/.rustc_info.json" || -f "$d/CACHEDIR.TAG" ||
     -d "$d/debug/.fingerprint" || -d "$d/release/.fingerprint" ||
     -d "$d/debug/deps" || -d "$d/release/deps" ]]
}

printf 'Repository: %s\nMode: %s\n' "$repo" "$mode"
printf 'Filesystem free space before:\n'
df -h -- "$repo" || true
printf '\nBenchmark-local target directories:\n'
mapfile -d '' candidates < <(find -P "$repo/benchmarks" -type d -name target -prune -print0)
targets=()
for d in "${candidates[@]}"; do
  if [[ -L "$d" ]]; then
    printf '  SKIP symlink: %s\n' "$d"
  elif is_cargo_target "$d"; then
    du -sh -- "$d" 2>/dev/null || printf '  %s (size unavailable)\n' "$d"
    targets+=("$d")
  else
    printf '  SKIP unrecognized target (inspect manually): %s\n' "$d"
  fi
done
((${#targets[@]})) || echo '  No recognized benchmark-local Cargo targets found.'
printf '\nPreserved: %s/target/ (root benchmark evidence and build artifacts)\n' "$repo"

podman_available=false
if command -v podman >/dev/null 2>&1; then
  if podman info >/dev/null 2>&1; then
    podman_available=true
    printf '\nPodman context (current user):\n'
    podman info --format '  driver={{.Store.GraphDriverName}} root={{.Store.GraphRoot}}' 2>/dev/null || true
    printf 'Stopped Podman containers eligible for pruning:\n'
    podman ps -a --filter status=exited --format '  {{.ID}} {{.Names}} {{.Status}}' || true
    echo '  Podman may also prune other non-running containers under its rules.'
  else
    echo 'Podman installed but unavailable; skipping Podman cleanup.' >&2
  fi
else
  echo 'Podman not installed; skipping Podman cleanup.'
fi

if [[ "$mode" == dry-run ]]; then
  echo
  echo "DRY RUN: no files or containers removed. Use --apply to execute."
  if [[ "$allow_repair" == true || "$allow_reset" == true ]]; then
    echo 'Repair/reset flags are inactive in dry-run mode.'
  fi
  exit 0
fi

if [[ "$yes" != true ]]; then
  [[ -t 0 ]] || { echo 'Noninteractive input: use --apply --yes for ordinary cleanup.' >&2; exit 2; }
  printf '\nDelete %d benchmark-local Cargo targets and prune stopped Podman containers? Type DELETE: ' "${#targets[@]}"
  read -r answer
  [[ "$answer" == DELETE ]] || { echo 'Cancelled.'; exit 0; }
fi

failed=0
podman_failed=0
for d in "${targets[@]}"; do
  # Revalidate location, target identity, and every path component immediately
  # before removal; do not traverse symlinked ancestors.
  case "$d" in "$repo"/benchmarks/*/target|"$repo"/benchmarks/*/target/*) ;; *)
    printf 'REFUSING unexpected path: %s\n' "$d" >&2; failed=1; continue ;;
  esac
  ancestor=$(dirname -- "$d")
  safe=true
  while [[ "$ancestor" != "$repo/benchmarks" && "$ancestor" != "$repo" && "$ancestor" != / ]]; do
    if [[ -L "$ancestor" ]]; then safe=false; break; fi
    ancestor=$(dirname -- "$ancestor")
  done
  if [[ "$safe" == true && ! -L "$d" && -d "$d" ]] && is_cargo_target "$d"; then
    printf 'Removing: %s\n' "$d"
    rm -rf -- "$d" || failed=1
  else
    printf 'Skipping changed/unsafe/absent target: %s\n' "$d"
  fi
done

if [[ "$podman_available" == true ]]; then
  # Capture Podman failures without suppressing or reclassifying the exit status.
  # A temporary private log is used only for diagnosis, never for evidence reuse.
  logdir=$(mktemp -d "${TMPDIR:-/tmp}/quervant-podman.XXXXXXXX") || exit 1
  chmod 700 "$logdir"
  trap 'rm -rf -- "$logdir"' EXIT
  echo 'Pruning stopped Podman containers:'
  if podman container prune --force >"$logdir/prune.log" 2>&1; then
    cat "$logdir/prune.log"
    echo 'Podman container prune succeeded.'
  else
    cat "$logdir/prune.log" >&2
    echo 'Podman container prune failed; investigating without changing storage.' >&2
    podman_failed=1

    # Do not interpret unrelated auth/permission/network failures as corruption.
    storage_error=false
    if grep -Eiq 'overlay|lowerdir|upperdir|workdir|determining size of layer|creating overlay mount|Unmounting .*merged|containers/storage/|storage.*corrupt' "$logdir/prune.log"; then
      storage_error=true
    fi

    check_supported=false
    check_failed=false
    if podman system check --help >"$logdir/check-help.log" 2>&1; then
      check_supported=true
      echo 'Running read-only Podman storage check:'
      if podman system check >"$logdir/check.log" 2>&1; then
        cat "$logdir/check.log"
      else
        check_failed=true
        cat "$logdir/check.log" >&2
      fi
      if grep -Eiq 'corrupt|damaged|inconsistent|missing.*layer|overlay|storage.*error' "$logdir/check.log"; then
        storage_error=true
      fi
    else
      echo 'Podman system check is unsupported by this Podman version.' >&2
    fi

    if [[ "$storage_error" != true ]]; then
      echo 'No recognized storage-layer error: refusing repair/reset. Investigate manually.' >&2
    else
      if [[ "$allow_repair" == true && "$check_supported" == true ]]; then
        echo 'Repair opt-in enabled: Podman may delete damaged images during repair.' >&2
        if [[ "$yes" != true ]]; then
          if [[ ! -t 0 ]]; then
            echo 'Repair requires --yes or interactive confirmation.' >&2
            exit 2
          fi
          printf 'Type REPAIR to authorize podman system check --repair: '
          read -r approval
          if [[ "$approval" != REPAIR ]]; then
            echo 'Repair declined.' >&2
            allow_repair=false
          fi
        fi
        if [[ "$allow_repair" == true ]]; then
          if podman system check --repair >"$logdir/repair.log" 2>&1; then
            cat "$logdir/repair.log"
          else
            cat "$logdir/repair.log" >&2
            echo 'Podman repair failed.' >&2
          fi
          echo 'Retrying container prune after repair:'
          if podman container prune --force >"$logdir/retry.log" 2>&1; then
            cat "$logdir/retry.log"
            podman_failed=0
            echo 'Podman container prune recovered.'
          else
            cat "$logdir/retry.log" >&2
            echo 'Podman container prune still failing.' >&2
          fi
        fi
      elif [[ "$allow_repair" == true ]]; then
        echo 'Cannot run requested repair: podman system check is unavailable.' >&2
      fi

      # Reset is only considered following a genuine storage-layer error,
      # with unresolved prune failure, explicit opt-in and a separate TTY approval.
      if ((podman_failed)) && [[ "$allow_reset" == true ]]; then
        if [[ ! -t 0 ]]; then
          echo 'RESET REFUSED: requires interactive TTY, even with --yes.' >&2
        else
          echo >&2
          echo 'DANGER: podman system reset destroys ALL local containers, pods,' >&2
          echo 'images, networks, volumes, and build cache for this Podman context.' >&2
          echo 'This may destroy Quervant local development database data.' >&2
          podman info --format 'Storage root: {{.Store.GraphRoot}}' 2>/dev/null >&2 || true
          printf 'To authorize irreversible reset, type RESET PODMAN STORAGE: ' >&2
          read -r reset_approval
          if [[ "$reset_approval" == 'RESET PODMAN STORAGE' ]]; then
            echo 'Executing explicitly authorized Podman storage reset.' >&2
            if podman system reset --force >"$logdir/reset.log" 2>&1; then
              cat "$logdir/reset.log"
              podman_failed=0
              echo 'Podman system reset succeeded. No post-reset prune necessary.'
            else
              cat "$logdir/reset.log" >&2
              echo 'Podman system reset failed; manual recovery required.' >&2
            fi
          else
            echo 'Reset declined; Podman storage left unchanged.' >&2
          fi
        fi
      elif ((podman_failed)); then
        echo 'Podman storage NOT reset. Optional recovery requires explicit flags.' >&2
      fi
    fi
  fi
fi

printf '\nFilesystem free space after:\n'
df -h -- "$repo" || true
if ((failed || podman_failed)); then
  echo 'Completed with one or more cleanup errors; see Podman diagnostics above.' >&2
  exit 1
fi
echo 'Cleanup completed.'
