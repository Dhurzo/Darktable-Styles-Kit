#!/usr/bin/env bash
#
# dtstylekit setup script — preset library bootstrap.
#
# dtstylekit needs the 534 official darktable styles (the "preset
# library") to build its search index.  Those .dtstyle files live in the
# darktable source tree at data/styles/ — they are NOT vendored into the
# dtstylekit repo.  This script:
#
#   1. Locates the darktable checkout (or a directory with .dtstyle files):
#        a. $DTSTYLEKIT_PRESETS_DIR  (explicit override, highest priority)
#        b. <dtstylekit parent's parent>/data/styles  (darktable checkout)
#        c. interactive prompt for a custom path
#   2. Creates/repairs the data/presets symlink pointing at it (a valid
#      existing symlink is left untouched).
#   3. Verifies at least one .dtstyle file is reachable.
#   4. Builds the preset search index (dtstylekit preset index).
#
# Idempotent: safe to run multiple times.
#
set -euo pipefail

# Resolve the directory this script lives in (works via symlinks).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRESETS_LINK="${SCRIPT_DIR}/data/presets"

info()  { printf '\033[1;34m[setup]\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[setup]\033[0m %s\n' "$*" >&2; }
die()   { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Locate the preset library
# ---------------------------------------------------------------------------
find_presets_dir() {
  # a. Explicit override
  if [[ -n "${DTSTYLEKIT_PRESETS_DIR:-}" ]]; then
    if [[ -d "${DTSTYLEKIT_PRESETS_DIR}" ]]; then
      printf '%s' "${DTSTYLEKIT_PRESETS_DIR}"
      return 0
    fi
    warn "DTSTYLEKIT_PRESETS_DIR is set but not a directory: ${DTSTYLEKIT_PRESETS_DIR}"
  fi

  # b. darktable checkout: dtstylekit lives inside <checkout>/dtstylekit
  local candidate="${SCRIPT_DIR}/../data/styles"
  if [[ -d "${candidate}" ]] && compgen -G "${candidate}/*.dtstyle" >/dev/null; then
    printf '%s' "${candidate}"
    return 0
  fi

  # c. Interactive prompt
  if [[ -t 0 ]]; then
    printf 'Enter the path to a darktable checkout or a directory of .dtstyle files: ' >&2
    read -r custom
    if [[ -n "${custom}" ]] && [[ -d "${custom}" ]]; then
      printf '%s' "${custom}"
      return 0
    fi
    die "That path does not exist."
  fi

  die "Preset library not found.
  Options:
    - export DTSTYLEKIT_PRESETS_DIR=/path/to/darktable/data/styles
    - clone darktable:  git clone https://github.com/darktable-org/darktable
      then run this script again (dtstylekit is expected to live inside
      the checkout, or pass DTSTYLEKIT_PRESETS_DIR)."
}

# ---------------------------------------------------------------------------
# 2. Create/repair the symlink
# ---------------------------------------------------------------------------
ensure_symlink() {
  local target="$1"

  if [[ -L "${PRESETS_LINK}" ]]; then
    local current
    current="$(readlink "${PRESETS_LINK}")"
    # Resolve both sides; if they point at the same directory, leave alone.
    if [[ "$(cd "$(dirname "${PRESETS_LINK}")" && readlink -f "${PRESETS_LINK}" 2>/dev/null || true)" \
          == "$(readlink -f "${target}")" ]]; then
      ok "Preset symlink already valid: ${PRESETS_LINK} -> ${current}"
      return 0
    fi
    warn "Replacing stale preset symlink: ${PRESETS_LINK} -> ${current}"
    rm "${PRESETS_LINK}"
  elif [[ -e "${PRESETS_LINK}" ]]; then
    die "${PRESETS_LINK} exists but is not a symlink — remove it manually first."
  fi

  mkdir -p "$(dirname "${PRESETS_LINK}")"
  ln -s "${target}" "${PRESETS_LINK}"
  ok "Created preset symlink: ${PRESETS_LINK} -> ${target}"
}

# ---------------------------------------------------------------------------
# 3. Verify + 4. index
# ---------------------------------------------------------------------------
main() {
  info "dtstylekit setup — preset library bootstrap"

  local presets_dir
  presets_dir="$(find_presets_dir)"
  info "Using preset library: ${presets_dir}"

  ensure_symlink "${presets_dir}"

  local count
  count="$(compgen -G "${PRESETS_LINK}/*.dtstyle" | wc -l)"
  if [[ "${count}" -lt 1 ]]; then
    die "No .dtstyle files reachable via ${PRESETS_LINK}"
  fi
  ok "Found ${count} preset(s)"

  # 4. Build the search index.  Prefer the project venv if present.
  local python=dtstylekit
  if [[ -x "${SCRIPT_DIR}/.venv/bin/dtstylekit" ]]; then
    python="${SCRIPT_DIR}/.venv/bin/dtstylekit"
  fi

  info "Building preset index (this can take a few minutes)..."
  "${python}" preset index --force
  ok "Done. dtstylekit is ready: try 'dtstylekit generate photo.jpg --references \"refs/*.jpg\"'"
}

main "$@"
