#!/usr/bin/env bash
# Install Flagship from a reviewed local checkout into a private Python venv.
set -Eeuo pipefail

usage() {
  printf '%s\n' 'Usage: bash scripts/bootstrap.sh [--yes] [--skip-system-packages]' \
    'Run as your normal Ubuntu user. --yes accepts the APT package installation.'
}
accept=()
system_packages=1
for argument in "$@"; do
  case "$argument" in
    --yes) accept=(-y) ;;
    --skip-system-packages) system_packages=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
if [[ $EUID -eq 0 ]]; then
  printf '%s\n' 'Run this script as your normal user, not with sudo. It requests sudo only for APT.' >&2
  exit 1
fi
if [[ $(uname -s) != Linux || ! -r /etc/os-release ]]; then
  printf '%s\n' 'Flagship requires Linux. On Windows, run this inside Ubuntu on WSL2.' >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ ${ID:-} != ubuntu ]]; then
  printf '%s\n' 'This bootstrap supports Ubuntu. Install the package manually on other Linux hosts.' >&2
  exit 1
fi
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
case "$source_dir" in
  /mnt/[a-z]/*)
    printf '%s\n' 'Clone FlagshipOS inside your Linux home directory before installing; Windows-mounted checkouts can reject Python build operations.' >&2
    exit 1
    ;;
esac
data_dir=${XDG_DATA_HOME:-"$HOME/.local/share"}/flagship
bin_dir="$HOME/.local/bin"
target="$data_dir/venv/bin/flagship"
if [[ -e "$bin_dir/flagship" || -L "$bin_dir/flagship" ]]; then
  if [[ ! -L "$bin_dir/flagship" || $(readlink -- "$bin_dir/flagship") != "$target" ]]; then
    printf '%s\n' "Refusing to overwrite existing command: $bin_dir/flagship" >&2
    exit 1
  fi
fi
if (( system_packages )); then
  sudo apt-get update
  sudo apt-get install "${accept[@]}" --no-install-recommends \
    python3 python3-venv podman distrobox uidmap dbus-user-session \
    slirp4netns fuse-overlayfs ca-certificates
fi
for executable in python3 podman distrobox; do
  command -v "$executable" >/dev/null || { printf 'Missing dependency: %s\n' "$executable" >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or newer is required")'
umask 077
mkdir -p -- "$data_dir" "$bin_dir"
python3 -m venv "$data_dir/venv"
"$data_dir/venv/bin/python" -m pip install --disable-pip-version-check "$source_dir"
if [[ ! -L "$bin_dir/flagship" ]]; then
  ln -s -- "$target" "$bin_dir/flagship"
fi
printf '\nInstalled %s\n' "$bin_dir/flagship"
printf '%s\n' 'Next: ~/.local/bin/flagship doctor' \
  'If flagship is not on your PATH, add $HOME/.local/bin or start a new login shell.' \
  'No tool containers have been created. Use flagship plan kali to review the first environment.'
