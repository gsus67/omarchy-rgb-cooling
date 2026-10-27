#!/usr/bin/env bash
# Removes everything the plugin added (see docs/API.md, "Footprint"): its user
# units, built core, state, settings, and the engines it installed itself. It
# never removes packages that were installed before the plugin.
set -euo pipefail
keep_settings=false
case ${1:-} in
  "") ;;
  --keep-settings) keep_settings=true ;;
  # Kept for compatibility: removing settings is now the default.
  --purge) ;;
  *) echo "Usage: bash uninstall.sh [--keep-settings]" >&2; exit 2 ;;
esac

id=io.github.gsus67.omarchy-rgb-cooling
name=omarchy-rgb-cooling
config_root="${XDG_CONFIG_HOME:-$HOME/.config}"
state_root="${XDG_STATE_HOME:-$HOME/.local/state}"
runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
state="$state_root/$name"
units="$config_root/systemd/user"
plugin="$config_root/omarchy/plugins/$id"

systemctl --user disable --now "$name.socket" 2>/dev/null || true
systemctl --user stop "$name.service" "$name-openrgb.service" 2>/dev/null || true

# Engines first: the helper lives in the plugin folder that is removed next.
# Removing packages needs the user's password (pkexec); if it is cancelled,
# say exactly what is left and how to remove it, then keep going.
engines="$plugin/bin/omarchy-rgb-engines"
if [[ -f $state/engines.json && -x $engines ]]; then
  if ! "$engines" uninstall-all; then
    echo "Engines installed by this plugin were not removed." >&2
    echo "Remove them later with: sudo pacman -Rns openrgb" >&2
  fi
fi

omarchy plugin disable "$id" 2>/dev/null || true
if [[ -d $plugin ]]; then
  omarchy plugin remove "$id" --yes
fi

# Every path bootstrap.py recorded, but only inside the project's own places.
# Lines ending in "/" are directories bootstrap created; they are removed only
# if empty, deepest first, so nothing that existed before is touched.
ledger="$state/installed-files"
dirs=()
if [[ -f $ledger ]]; then
  while IFS= read -r path; do
    [[ -z $path ]] && continue
    if [[ $path == */ ]]; then
      case $path in
        "$units"/|"$units"/*.wants/|"$config_root"/systemd/) dirs+=("${path%/}") ;;
        *) echo "Skipping unexpected ledger entry: $path" >&2 ;;
      esac
      continue
    fi
    case $path in
      "$state"/*|"$units/$name".*|"$units/$name"-*.service|"$units"/*.wants/"$name".*)
        rm -f -- "$path" ;;
      *) echo "Skipping unexpected ledger entry: $path" >&2 ;;
    esac
  done < "$ledger"
fi
rm -f -- "$units/$name.socket" "$units/$name.service" "$units/$name"-*.service \
  "$units"/*.wants/"$name".*
if [[ ${#dirs[@]} -gt 0 ]]; then
  while IFS= read -r dir; do
    rmdir -- "$dir" 2>/dev/null || true
  done < <(printf '%s\n' "${dirs[@]}" | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-)
fi
systemctl --user daemon-reload 2>/dev/null || true

rm -rf -- "$state"
rm -f -- "$runtime/$name.sock"
if ! $keep_settings; then rm -rf -- "${config_root:?}/$name"; fi
echo 'Omarchy RGB & Cooling uninstalled.'
