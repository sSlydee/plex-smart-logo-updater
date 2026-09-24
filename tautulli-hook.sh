#!/usr/bin/env bash
# Tautulli hook: processes titles as soon as Plex adds them.
#
# Tautulli > Settings > Notification Agents > Add a new notification agent > Script
#   Script Folder: this folder          Script File: tautulli-hook.sh
#   Triggers: Recently Added            Arguments (Recently Added): {rating_key}
#
# The run (dry run + review page + notification) is started in the background so
# Tautulli is not kept waiting; its output goes to logs/tautulli.log.
cd "$(dirname "$0")" || exit 1

args=()
for value in "$@"; do
    [[ "$value" =~ ^[0-9]+$ ]] && args+=(--rating-key "$value")
done
[ ${#args[@]} -eq 0 ] && { echo "tautulli-hook.sh: no ratingKey given" >&2; exit 0; }

mkdir -p logs
if command -v setsid >/dev/null 2>&1; then detach=(setsid); else detach=(); fi
nohup "${detach[@]}" .venv/bin/python plex-smart-logo-updater.py "${args[@]}" --html --notify --quiet \
    >> logs/tautulli.log 2>&1 < /dev/null &
echo "plex-smart-logo-updater started for: $*"
