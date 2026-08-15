#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/retropyclip"
log_file="$state_dir/tray.log"
tray_launcher="$project_dir/.venv/bin/retropyclip-tray"
extension_uuid="retropyclip@vaughndv.github.io"
extension_source="$project_dir/packaging/gnome-shell-extension"
extension_target="${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/$extension_uuid"
gnome_bridge=false
gnome_restart_required=false

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This updater is intended for Linux."
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not installed. Follow https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

session_type="${XDG_SESSION_TYPE:-unknown}"
desktop_name="${XDG_CURRENT_DESKTOP:-unknown}"
echo "Desktop session: $desktop_name ($session_type)"
case "$session_type" in
    wayland)
        if ! command -v wl-copy >/dev/null 2>&1 || ! command -v wl-paste >/dev/null 2>&1; then
            echo "Installing the Wayland clipboard utility…"
            sudo apt-get update
            sudo apt-get install -y wl-clipboard
        fi
        if [[ "$desktop_name" == *GNOME* || "$desktop_name" == *ubuntu* ]]; then
            gnome_bridge=true
        fi
        ;;
    x11)
        if ! command -v xclip >/dev/null 2>&1 && ! command -v xsel >/dev/null 2>&1; then
            echo "Installing the X11 clipboard utility…"
            sudo apt-get update
            sudo apt-get install -y xclip
        fi
        ;;
    *)
        echo "Warning: XDG_SESSION_TYPE is '$session_type'; desktop clipboard support may be unavailable."
        ;;
esac

if [[ "$gnome_bridge" == true ]]; then
    echo "Installing the RetroPyClip GNOME clipboard bridge…"
    install -d -m 700 "$extension_target"
    install -m 600 "$extension_source/extension.js" "$extension_target/extension.js"
    install -m 600 "$extension_source/metadata.json" "$extension_target/metadata.json"

    enabled_extensions="$(python3 - "$extension_uuid" "$(gsettings get org.gnome.shell enabled-extensions)" <<'PY'
import ast
import sys

uuid = sys.argv[1]
raw = sys.argv[2]
if raw.startswith("@as "):
    raw = raw[4:]
enabled = ast.literal_eval(raw)
if uuid not in enabled:
    enabled.append(uuid)
print(repr(enabled))
PY
    )"
    gsettings set org.gnome.shell enabled-extensions "$enabled_extensions"
    if gnome-extensions info "$extension_uuid" >/dev/null 2>&1; then
        gnome-extensions disable "$extension_uuid" >/dev/null 2>&1 || true
        gnome-extensions enable "$extension_uuid" >/dev/null 2>&1 || true
    fi
    if ! gnome-extensions list --active 2>/dev/null | grep -Fxq "$extension_uuid"; then
        gnome_restart_required=true
    fi
fi

cd "$project_dir"
echo "Updating the RetroPyClip environment…"
uv sync --extra gui --locked
uv run retropyclip doctor

if [[ -x "$tray_launcher" ]]; then
    while IFS= read -r tray_pid; do
        [[ "$tray_pid" =~ ^[0-9]+$ ]] || continue
        tray_command="$(ps -p "$tray_pid" -o command= 2>/dev/null || true)"
        if [[ "$tray_command" == *"$tray_launcher"* ]]; then
            echo "Stopping the previous RetroPyClip tray process…"
            kill -TERM "$tray_pid"
        fi
    done < <(pgrep -f -- "$tray_launcher" || true)

    for _ in {1..50}; do
        pgrep -f -- "$tray_launcher" >/dev/null 2>&1 || break
        sleep 0.1
    done
fi

install -d -m 700 "$state_dir"
: >"$log_file"
chmod 600 "$log_file"

echo "Starting RetroPyClip…"
setsid --fork uv run retropyclip-tray </dev/null >>"$log_file" 2>&1

for _ in {1..50}; do
    if pgrep -f -- "$tray_launcher" >/dev/null 2>&1; then
        echo "RetroPyClip is updated and running."
        echo "Diagnostic log: $log_file"
        if [[ "$gnome_restart_required" == true ]]; then
            echo
            echo "One-time GNOME step required: log out and back in, then run ./ubuntu-update.sh again."
        elif [[ "$gnome_bridge" == true ]]; then
            echo "GNOME clipboard bridge: active"
        fi
        exit 0
    fi
    sleep 0.1
done

echo "RetroPyClip did not start. Check: $log_file"
exit 1
