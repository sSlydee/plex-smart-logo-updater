# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and the project uses [semantic versioning](https://semver.org/).

## [1.5.0] - 2026-09-25

### Added
- Quebec posters: with `--posters` (or `PLEX_POSTERS=yes`, asked by the setup wizard), the poster of each title whose Quebec title differs is read with OCR; a Quebec poster is replaced with one showing the French (or original) title, picked among the first 30 posters. Other posters are never touched.
- Poster changes use the same review page (new "Posters" filter), undo journal, notifications and ignore list as the logos; a rejected poster is ignored as `<ratingKey>:poster`, without ignoring the title's logo.

## [1.4.0] - 2026-09-25

### Added
- Tautulli running in a container (common on seedboxes): `tautulli-hook.sh` now queues the added titles (`logs/tautulli-queue.txt`); `--process-queue` processes the queue, and `configure.py --tautulli` installs a cron job that does it every 5 minutes (nothing happens when the queue is empty).
- The hook still processes the queue immediately when it can run the script's Python environment.

## [1.3.1] - 2026-09-24

### Fixed
- Logos with widely spaced letters could be read out of order ("U R S E" for "RUSE"), so a Quebec logo was not detected (e.g. *Sharper*). OCR text is now assembled in reading order; cached readings are redone once.

## [1.3.0] - 2026-09-24

### Added
- Tautulli integration: `tautulli-hook.sh` runs the script as soon as Plex adds a title ("Recently Added" trigger), in the background.
- `--rating-key`: only process the given titles; an episode or a season counts as its show.
- Uptime Kuma monitoring: `HEALTHCHECK_URL` is pinged after every run (up, or down with the reason); healthchecks.io URLs work too. The setup wizard asks for it.

### Changed
- In targeted runs, a pending change is notified only once (a season imported episode by episode sends one notification); the weekly run still reminds you of pending changes.
- Runs wait for each other instead of running at the same time, and every run gets its own logs folder.

## [1.2.1] - 2026-09-24

### Fixed
- A locked logo field **without** a logo (e.g. after removing a logo in Plex) was silently skipped; it now gets a proposal like any title without a logo. Rejecting it in the review page puts the title on the ignore list.
- `--undo` restores the lock of a field that was locked and empty before the change.

## [1.2.0] - 2026-09-24

### Added
- Ignore list (`ignored.json`): ignored titles are skipped and tagged `[IGNORED]`, so they are neither proposed again nor notified on every run.
- Titles rejected in the review page are added to the ignore list when applying with `--choices`.
- `--ignore`, `--unignore` and `--list-ignored`; titles can be given as `Library/Title`, `Title`, `Title (year)` or a ratingKey.

## [1.1.0] - 2026-09-24

### Added
- `PLEX_LANGUAGES=auto`, the new default: each library uses its own language (as set in Plex), then English. A French library gets French logos (with the Quebec logo detection), a German one German logos, an English one English logos.
- Each library log shows the languages it uses.
- The setup wizard recommends `auto` and lists the language of the selected libraries.

### Changed
- The Quebec logo detection is skipped for Quebec French (`fr-CA`) libraries.
- A fixed list (e.g. `PLEX_LANGUAGES=fr-FR,en-US`) keeps working and still applies to every library.

## [1.0.0] - 2026-09-24

First release.

### Logo selection
- Sets on titles without a logo the logo Plex itself recommends for the library language, with fallback languages (`PLEX_LANGUAGES`, French then English by default), and finds it among the server's candidates.
- Never touches hand-picked (locked) logos, nor logos already set by Plex unless they are Quebec logos.

### Quebec (French-Canadian) logo detection
- Reads logo text with OCR when the Quebec title differs from the French one.
- Replaces Quebec logos set by Plex with the logo closest to the full French title, otherwise the original title; prefers logos without extra text (actor names, taglines), then the same style (colored or white), then Plex's pick, then the largest.
- Never adds a Quebec logo; titles with only Quebec logos are reported for manual handling.
- Special mentions for less certain picks: French inferred, original title, not verified.
- OCR results are cached (`.cache-ocr.json`).

### Safety and review
- Dry run by default; `--apply` to change Plex.
- Self-contained HTML review page (`--html`): approve or reject each change, export `choices.json`, apply only approved changes with `--choices`.
- Undo journal (`undo.json`) for every application, and `--undo` to restore the previous state.
- Per-library logs with a summary, automatic pruning of old dry-run logs (`PLEX_LOGS_KEEP`).

### Setup and automation
- `install.sh` and a setup wizard (`configure.py`) with a Plex connection test, library picker, webhook test and cron setup; single steps can be redone (`--token`, `--libraries`, `--notifications`, `--cron`…).
- Notifications to Discord, Bark or any JSON webhook (`--notify`), sent only when there is something to do; clear message and notification when the Plex token is rejected.

[1.5.0]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.5.0
[1.4.0]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.4.0
[1.3.1]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.3.1
[1.3.0]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.3.0
[1.2.1]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.2.1
[1.2.0]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.2.0
[1.1.0]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.1.0
[1.0.0]: https://github.com/sSlydee/plex-smart-logo-updater/releases/tag/v1.0.0
