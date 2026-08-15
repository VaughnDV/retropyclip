#!/usr/bin/env bash

set -Eeuo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/retropyclip"
log_file="$state_dir/tray.log"
tray_launcher="$project_dir/.venv/bin/retropyclip-tray"

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
            echo "Note: GNOME Wayland may block global clipboard watching."
            echo "RetroPyClip will stay quiet instead of using visible fallback polling."
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
        exit 0
    fi
    sleep 0.1
done

echo "RetroPyClip did not start. Check: $log_file"
exit 1
