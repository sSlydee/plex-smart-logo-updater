#!/usr/bin/env bash
# Tautulli hook: queues the titles Plex just added, so they are processed right away.
#
# Tautulli > Settings > Notification Agents > Add a new notification agent > Script
#   Script Folder: this folder          Script File: tautulli-hook.sh
#   Triggers: Recently Added            Arguments (Recently Added): {rating_key}
#
# The ratingKeys are appended to logs/tautulli-queue.txt. When this machine can run
# the script's Python environment, the queue is processed immediately in the
# background (dry run + review page + notification, output in logs/tautulli.log).
# When Tautulli runs in a container that cannot (a common setup), the cron job
# installed by `configure.py --tautulli` processes the queue every few minutes.
cd "$(dirname "$0")" || exit 1

keys=()
for value in "$@"; do
    [[ "$value" =~ ^[0-9]+$ ]] && keys+=("$value")
done
[ ${#keys[@]} -eq 0 ] && { echo "tautulli-hook.sh: no ratingKey given" >&2; exit 0; }

mkdir -p logs
printf '%s\n' "${keys[@]}" >> logs/tautulli-queue.txt
echo "plex-smart-logo-updater: queued ${keys[*]}"

if .venv/bin/python -c "import plexapi" >/dev/null 2>&1; then
    if command -v setsid >/dev/null 2>&1; then detach=(setsid); else detach=(); fi
    nohup "${detach[@]}" .venv/bin/python plex-smart-logo-updater.py --process-queue --html --notify --quiet \
        >> logs/tautulli.log 2>&1 < /dev/null &
fi
