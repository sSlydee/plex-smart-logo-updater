"""
State files kept in a run's logs folder, shared by plex-smart-logo-updater.py
(which writes them) and review_server.py (which reads them).

- run.json: what the run covered, written at its start (complete: false) and
  completed at its end, so an interrupted or still running run is recognizable.
- applied.json: in a dry run's folder, once its choices were applied (from the
  review server or from the command line).
"""
import json
import os
import re
import time

RUN_FILE = "run.json"
APPLIED_FILE = "applied.json"
# Dry-run folders: "2026-09-29_21h02m52_simulation", or "..._simulation_2" for a second run the same second
DRY_RUN_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}h\d{2}m\d{2}_simulation(_\d+)?$")


def now():
    return time.strftime("%Y-%m-%d %H:%M")


def is_dry_run_folder(folder):
    return bool(DRY_RUN_NAME.match(os.path.basename(os.path.normpath(folder))))


def read(folder, name):
    try:
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write(folder, name, data):
    tmp = os.path.join(folder, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(folder, name))


def write_run_info(folder, targeted, libraries, complete):
    """run.json: targeted = limited to some titles (Tautulli, --rating-key, a choices file)."""
    info = read(folder, RUN_FILE) or {"started": now()}
    info.update(targeted=bool(targeted), libraries=sorted(libraries), complete=bool(complete))
    if complete:
        info["finished"] = now()
    try:
        write(folder, RUN_FILE, info)
    except OSError:
        pass


def mark_applied(dry_run_folder, application_folder):
    """Records that a dry run's choices were applied from the command line (unless already recorded)."""
    if not is_dry_run_folder(dry_run_folder) or read(dry_run_folder, APPLIED_FILE) is not None:
        return
    try:
        write(dry_run_folder, APPLIED_FILE, {"started": now(), "finished": now(), "exit": 0, "pid": None,
                                             "application": os.path.basename(os.path.normpath(application_folder))})
    except OSError:
        pass
