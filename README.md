# Plex Smart Logo Updater

[![Tests](https://github.com/sSlydee/plex-smart-logo-updater/actions/workflows/tests.yml/badge.svg)](https://github.com/sSlydee/plex-smart-logo-updater/actions/workflows/tests.yml) [![Release](https://img.shields.io/github/v/release/sSlydee/plex-smart-logo-updater)](https://github.com/sSlydee/plex-smart-logo-updater/releases) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Plex logos (ClearLogo) in the language of each library, with English as a fallback. In French libraries, it also replaces the French-Canadian (Quebec) logos that Plex picks by mistake, and optionally the Quebec posters.**

🇫🇷 [Version française](README.fr.md)

![Review page: Quebec logos (left) replaced with French logos (right)](docs/review-quebec.png)

## Why

- **Many titles have no logo.** Plex only sets a logo automatically when one exists in the library's language. In a French, German or Spanish library, a title stays without a logo even when a good English one exists. This happens a lot with anime and foreign films.
- **French libraries get Quebec logos.** Plex does not tell French (France) from French (Quebec) apart. *The Banker* can end up with a logo reading "Le financier", and *Edge of Tomorrow* with "Un jour sans lendemain".
- **The same goes for posters.** *Bad Boys 2* can show "Mauvais garçons II" and *Land of Bad* can show "Territoire hostile".

## What it does

- **Adds the missing logos.** For a title without a logo, the script asks Plex for its recommended logo, first in the library's language and then in English. This is the logo Plex would have picked itself, and no TMDB key is needed.
- **Replaces Quebec logos**, and optionally Quebec posters. It reads the text on the image (OCR) and compares it with the French, Quebec and original titles.
- **Leaves everything else alone.** An existing logo is kept unless it is a Quebec one. A logo or poster you picked yourself (a locked field) is never replaced.
- **Changes nothing until you approve.** Each run is a dry run by default. A review page shows every change (before and after) so you can approve or reject it. Every application can be undone.
- **Can run on its own.** It can scan your libraries on a schedule (daily or weekly), check new titles as soon as Plex adds them (with Tautulli), and send you a notification (Discord, Bark…) when there is something to review.

Based on [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater) (MIT license).

## Contents

- [Quick start](#quick-start)
- [Installation, step by step](#installation-step-by-step)
- [Everyday use](#everyday-use): dry run, review, apply, ignore list, undo
- [Automation](#automation): automatic run, notifications, Tautulli, Uptime Kuma
- [Reference](#reference): setup wizard, settings, options
- [How it works](#how-it-works): language choice, Quebec detection, posters
- [Logs](#logs)
- [Troubleshooting](#troubleshooting) · [Good to know](#good-to-know) · [Tests](#tests)

## Quick start

For those used to the command line. Linux (or macOS, or WSL on Windows), Python 3.8+ and git:

```bash
git clone https://github.com/sSlydee/plex-smart-logo-updater.git
cd plex-smart-logo-updater
./install.sh                                          # installs into .venv, then starts the setup wizard
.venv/bin/python plex-smart-logo-updater.py --html    # dry run + review page
```

Then follow the [everyday use](#everyday-use) steps.

## Installation, step by step

New to GitHub or to the command line? This guide takes you from nothing to your first dry run in about 10 minutes, most of it spent waiting for downloads.

### What you need

- **A machine that can reach your Plex server**: the Plex server itself, a seedbox, a NAS, a VPS… The script is tested on Linux. macOS should work, and on Windows use [WSL](https://learn.microsoft.com/windows/wsl/install).
- **Python 3.8 or later** and **git**.
- **Your Plex token** ([how to find it](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)).
- About **500 MB of disk space** for the Python environment. The OCR engine is the largest part.

### 1. Open a terminal on the machine

If the machine is remote, connect to it with SSH. On your computer, open a terminal (PowerShell on Windows, Terminal on macOS/Linux) and type:

```bash
ssh your_user@your_server_address
```

Then check that Python and git are installed:

```bash
python3 --version
git --version
```

Each command should print a version number, and Python must be 3.8 or later. If one is missing, install it with your system's package manager (on Debian/Ubuntu: `sudo apt install python3 python3-venv git`) or ask your provider.

### 2. Download the project

Cloning downloads the project and keeps a link to GitHub, so a single command updates it later:

```bash
cd ~
git clone https://github.com/sSlydee/plex-smart-logo-updater.git
cd plex-smart-logo-updater
```

### 3. Install

```bash
./install.sh
```

The installer creates a dedicated Python environment in the `.venv` folder, so nothing is installed system-wide. It downloads the dependencies (a few minutes), then starts the setup wizard.

### 4. Answer the setup wizard

Press Enter to accept the value shown in `[brackets]`.

1. **Plex server address**: the server's **local** address, with its port.
   - The script runs on the Plex server itself: `http://127.0.0.1:32400`.
   - Plex runs in Docker on the same machine: often `http://172.17.0.1:32400`.
   - Another machine on your network: `http://192.168.x.x:32400`.

   Avoid a public domain name behind a reverse proxy. The script sends many requests, and Fail2Ban or CrowdSec could block it.
2. **Plex token**: paste it. Nothing appears while you paste, which is normal. The wizard tests the connection right away.
3. **Libraries**: the numbers of the libraries to process, separated by commas (e.g. `1,3,4`), or `all`.
4. **Logo language**: keep `auto` (each library's own language, then English). The wizard then asks whether to also replace [Quebec posters](#quebec-posters).
5. **Notifications**: optional. Answer `n` to skip the webhooks, then leave the Uptime Kuma URL empty.
6. **Automatic run**: pressing Enter sets up a weekly dry run. Pick `never` (type `1`) if you would rather start by hand; you can add it later.

Your answers are saved in `config.env`, which only you can read.

### 5. First dry run

```bash
.venv/bin/python plex-smart-logo-updater.py --html
```

Nothing is changed in Plex. The first run takes a while (about 7 minutes for 300 movies) because it reads the logos. Later runs use a cache and are much faster. At the end, the summary shows what would change and where the review page is.

> Always run the script with `.venv/bin/python`, not `python3`: the dependencies are only installed in `.venv`.

### Updating

```bash
cd ~/plex-smart-logo-updater
git pull
./install.sh --no-config
```

`git pull` downloads the new version, and `./install.sh --no-config` updates the dependencies without asking the setup questions again. Your settings, logs and cache are kept. See [CHANGELOG.md](CHANGELOG.md) for what changed.

### Uninstalling

```bash
cd ~/plex-smart-logo-updater
.venv/bin/python configure.py --cron       # choose "never" to remove the automatic run
.venv/bin/python configure.py --tautulli   # Tautulli queue, if turned on: choose "off"
cd ~
rm -rf plex-smart-logo-updater
```

If you set up the Tautulli hook, also delete its Script agent in Tautulli. Logos and posters already set in Plex stay in place. To restore the previous ones first, [undo](#undoing-an-application) your applications before deleting the folder.

## Everyday use

Every change goes through three steps: a **dry run** that writes a review page, your **review**, then the **application** of what you approved.

### 1. Dry run

```bash
.venv/bin/python plex-smart-logo-updater.py --html
```

Each run creates a folder in `logs/`, named after the date and mode (`2026-09-23_18h20m05_simulation` for a dry run). With `--html`, the review page `review.html` is written there.

### 2. Review

Open `review.html` in your browser. It is a single self-contained file: the images are embedded, and it contains neither your server's address nor your token.

![Review page with all changes](docs/review-all.png)

- Each change shows the current image and the new one.
- Everything is **approved** by default: click **Reject** on the changes you do not want.
- Filters help you start with the doubtful cases ("Not verified", "Original title", "Posters"…).
- Your choices are kept in the browser if you close the page.
- When you are done, click **Export choices.json**.

If the script runs on a remote machine, copy the files with an SFTP client, using the same address and login as SSH: [WinSCP](https://winscp.net/) or [FileZilla](https://filezilla-project.org/) on Windows, [Cyberduck](https://cyberduck.io/) or FileZilla on macOS, or your file manager (`sftp://your_user@your_server_address`) on Linux. From a terminal on your computer:

```bash
scp your_user@your_server_address:plex-smart-logo-updater/logs/<folder>/review.html .
scp choices.json your_user@your_server_address:plex-smart-logo-updater/logs/<folder>/
```

### 3. Apply

Put `choices.json` in the dry run's folder, then:

```bash
.venv/bin/python plex-smart-logo-updater.py --apply --choices logs/<dry run folder>/choices.json
```

Only the approved changes are applied, and the rejected ones go to the [ignore list](#ignore-list). If Plex changed a title since the dry run, the title is left untouched and tagged `[RECHECK]`: run a new dry run.

To apply everything without the review page, run `--apply` without `--choices`. This is not recommended.

### Ignore list

Some titles should be left alone: a change you rejected, or a logo you removed on purpose. Without the ignore list, the automatic run would propose them again and notify you every time.

- **Rejected changes are remembered.** When you apply with `--choices`, each rejected change goes to the ignore list and is not proposed again. A rejected poster only ignores the poster, and the title's logo is still checked.
- **Add a title by hand** so the script never touches it again:

  ```bash
  .venv/bin/python plex-smart-logo-updater.py --ignore "Movies/Edge of Tomorrow"
  ```

  The title can be given as `Library/Title`, `Title`, `Title (year)` or a Plex ratingKey. If several titles match, the script lists them so you can be more specific.
- **Remove a title** with `--unignore "Edge of Tomorrow"`, and **show the list** with `--list-ignored`.

The list is stored in `ignored.json`, next to the script.

### Undoing an application

Each application records the previous state in `undo.json`, in its logs folder. To put everything back:

```bash
.venv/bin/python plex-smart-logo-updater.py --undo logs/<application folder>            # dry run
.venv/bin/python plex-smart-logo-updater.py --undo logs/<application folder> --apply    # restore
```

- Each logo or poster gets its previous image back, with its previous lock state. A title that had no logo goes back to having none.
- An image that changed since the application, whether you or Plex changed it, is left untouched.

## Automation

### Automatic run

The setup wizard can add an automatic run to cron (daily or weekly). It runs a **dry run** with the review page and notifications. **Nothing is ever applied automatically**: when there is something to review, you get a notification, you check the page, then you apply with `--choices`.

The output goes to `logs/cron.log` (kept under 5 MB). The wizard only manages its own crontab lines, tagged `# plex-smart-logo-updater`. To change the schedule: `.venv/bin/python configure.py --cron`.

### Notifications

With `--notify` (included in the automatic run), the script sends a summary **only when there is something to do**: changes to review, titles to handle by hand, or errors. A title to handle by hand is reported once. For changes still waiting for your review, each full run sends a reminder.

`NOTIFY_URLS` can hold several webhooks, separated by commas. The type is guessed from the address, or forced with a prefix:

| Service | Example in `NOTIFY_URLS` |
|---|---|
| Discord | `https://discord.com/api/webhooks/…` |
| Bark (official server) | `https://api.day.app/<your key>` |
| Bark (self-hosted) | `bark:https://my-bark-server.example/<your key>` |
| Generic webhook (POST JSON with `title`, `message`, `text`) | `json:https://example.org/hook` |

Webhook addresses are never written to the logs. To change them: `.venv/bin/python configure.py --notifications`.

### New titles right away, with Tautulli

With [Tautulli](https://tautulli.com/), new movies and shows are checked a few minutes after Plex adds them, instead of at the next automatic run.

In Tautulli, go to **Settings > Notification Agents > Add a new notification agent > Script**:

| Setting | Value |
|---|---|
| Script Folder | the project folder (the one containing `tautulli-hook.sh`) |
| Script File | `tautulli-hook.sh` |
| Triggers | **Recently Added** |
| Arguments > Recently Added | `{rating_key}` |

The hook adds the new title to a queue. If it can, it then processes the queue right away (dry run, review page, notification), with the output in `logs/tautulli.log`.

**Tautulli in a container** (common on seedboxes, for example with linuxserver images): the container can see the project folder but usually cannot run its Python environment. Two things change:

- In Tautulli, the Script Folder is the path **as the container sees it**, often `/home/<user>/...`.
- On the host, turn on queue processing with `.venv/bin/python configure.py --tautulli`. A cron job then processes the queue every 5 minutes, and does nothing when it is empty.

A few more details:

- An episode or a season counts as its show. Titles outside `PLEX_LIBRARIES` are skipped.
- A season imported episode by episode does not flood you: each pending change is notified once. The automatic run still sends a reminder while a change waits for your review.
- Runs started at the same time wait for each other.
- If Plex has not fetched a title's images yet when it is checked, the next automatic run catches it.

To process titles by hand: `--rating-key 12345`, or `--process-queue` for the queue.

### Monitoring with Uptime Kuma

With `HEALTHCHECK_URL`, every run pings a monitoring service. It reports **up** when the run went fine, and **down** with the reason when it failed (token rejected, server unreachable, crash). If the automatic run stops altogether (broken cron, machine turned off…), the missing ping warns you.

In [Uptime Kuma](https://github.com/louislam/uptime-kuma), go to **Add New Monitor > Push**. Copy the push URL into `HEALTHCHECK_URL`, or give it to `configure.py --notifications`. Then set the **heartbeat interval** a bit above your cron frequency, for example 8 days (691200 s) for a weekly run. A [healthchecks.io](https://healthchecks.io/) URL works too.

## Reference

### Setup wizard

`configure.py` writes `config.env`. Run it again at any time: the current values are offered as defaults, so press Enter to keep them.

```bash
.venv/bin/python configure.py
```

To redo a single step:

| Command | Effect |
|---|---|
| `configure.py --token` | Change **only the token**: it is prompted for, tested, then saved |
| `configure.py --server` | Server address and token |
| `configure.py --libraries` | Libraries to process |
| `configure.py --language` | Logo language and Quebec posters |
| `configure.py --notifications` | Webhooks and Uptime Kuma |
| `configure.py --cron` | Automatic run |
| `configure.py --tautulli` | Queue processing for Tautulli in a container |

A new token is only saved if Plex accepts it. **If your token changes**, the script stops with "Plex token rejected: change it with: .venv/bin/python configure.py --token", and also sends this message as a notification when run with `--notify`.

### Settings (`config.env`)

The wizard writes this file and makes it readable by you only, because it contains your token. You can also write it by hand from `config.env.example`.

| Variable | Purpose | Default / example |
|---|---|---|
| `PLEX_URL` | **Local** address of the Plex server | `http://192.168.1.100:32400` |
| `PLEX_TOKEN` | Your Plex token | |
| `PLEX_LIBRARIES` | Libraries to process, comma-separated | `Movies,TV Shows,Anime` |
| `PLEX_LANGUAGES` | Languages in order of preference. `auto`: each library's own language, then English | `auto`, or e.g. `fr-FR,en-US` for every library |
| `PLEX_POSTERS` | `yes`: also replace [Quebec posters](#quebec-posters) | `no` |
| `NOTIFY_URLS` | [Webhooks](#notifications) for `--notify`, comma-separated | |
| `HEALTHCHECK_URL` | [Uptime Kuma](#monitoring-with-uptime-kuma) push URL | |
| `PLEX_LOGS_DIR` | Logs folder | `logs/` next to the script |
| `PLEX_LOGS_KEEP` | Dry-run log folders to keep. Application folders (with `undo.json`) are always kept | `100` |
| `PLEX_OCR_CACHE` | OCR cache | `.cache-ocr.json` next to the script |
| `PLEX_IGNORE_FILE` | Ignore list | `ignored.json` next to the script |

A variable set when launching the script takes precedence over `config.env`. For example, to process a single library:

```bash
PLEX_LIBRARIES="Movies" .venv/bin/python plex-smart-logo-updater.py
```

### Options

| Option | Effect |
|---|---|
| *(none)* | Dry run: nothing is changed |
| `--html` | Write the review page `review.html` |
| `--apply` | Apply the changes |
| `--choices FILE` | With `--apply`: only apply the changes approved in the review page |
| `--posters` | Also replace [Quebec posters](#quebec-posters) (same as `PLEX_POSTERS=yes`) |
| `--fix-locked-quebec` | Also replace **locked** logos and posters detected as Quebec ones |
| `--notify` | Send a notification when there is something to do |
| `--quiet` | Only print the summary (the details stay in the logs) |
| `--rating-key KEY` | Only process these titles (Plex ratingKey) |
| `--process-queue` | Process the titles queued by the Tautulli hook |
| `--ignore TITLE` / `--unignore TITLE` / `--list-ignored` | Manage the [ignore list](#ignore-list) |
| `--undo FOLDER` | [Undo](#undoing-an-application) an application (dry run unless `--apply` is given) |
| `--replace` | Also replace logos set by Plex that differ from its current recommendation |
| `--replace --include-locked` | Also replace hand-picked logos (not recommended) |

`--help` lists all the options.

Be careful with `--replace`: on TMDB, a "French" logo is sometimes the Quebec version, and the OCR does not always catch it. That is why, by default, the script only replaces logos detected as Quebec ones.

When applying, the script waits 2 s after each change and 10 s every 10 changes, to spare the server. Temporary errors (429, 5xx) are retried up to 4 times.

## How it works

### Choosing a logo

For each title **without a logo**, the script asks Plex's metadata service (`metadata.provider.plex.tv`, with your token) which logo it recommends: first in the library's language, then in English. It looks for that logo among the ones your server offers (same address, or identical image) and selects it. It only downloads the logo from the Internet when your server does not have it.

A title that already has a logo keeps it, unless that logo is a Quebec one. A locked field *without* a logo gets a proposal like any other title without a logo. To keep it empty, reject the proposal: the title then goes to the ignore list.

### Quebec logo detection

This only applies to French libraries. When the French (fr-FR) and Quebec (fr-CA) titles given by Plex differ, the script **reads the text on the logo** (OCR) and compares it with the French, Quebec and original titles.

- **A Quebec logo set by Plex is replaced** with the best non-Quebec logo: the one closest to the full French title, otherwise to the original title. When several are equally close, it prefers, in this order: a logo without extra text (actor names, taglines; "Marvel Studios", "Disney"… are allowed), one in the same style as the replaced logo (colored or white), the one Plex recommends, then the largest one.
- **A Quebec logo is never added.** If Plex recommends one, the script looks for another.
- When the French title differs from the original title and Plex's pick is not clearly French, the script looks for a logo with the French title (e.g. "HAPPY BIRTHDEAD" rather than "HAPPY DEATH DAY"). When France keeps the original title, Plex's pick is kept.
- When Quebec keeps the original title (*Black Box Diaries*), a logo with that title is **not** a Quebec logo.
- If **only** Quebec logos exist, the title is tagged `[CHECK]`: pick one by hand.
- A **locked** Quebec logo is reported, and only replaced with `--fix-locked-quebec`.

The detection is deliberately cautious: an existing logo is only replaced when it is clearly read as a Quebec one. Three **special mentions** flag the logos set with less certainty, and the review page has a filter for each:

| Mention | Meaning |
|---|---|
| `[FRENCH INFERRED]` | The French title is read on the logo, and the words specific to the Quebec title are missing (e.g. "PUSH" when Quebec says "Push : La division"). Very likely correct. |
| `[ORIGINAL TITLE]` | The logo shows the original title, neither French nor Quebec (e.g. "HAPPY DEATH DAY" for *Happy Birthdead*). |
| `[NOT VERIFIED]` | The OCR could not read the logo (very stylized font, spaced-out letters…). It is set anyway, as Plex would have done: **check it**. |

The OCR readings are cached (`.cache-ocr.json`), so a new run only reads new images.

### Quebec posters

This check is optional: turn it on with `--posters`, or `PLEX_POSTERS=yes` (the wizard asks). It works like the logo detection, in French libraries, for titles whose Quebec title differs:

- The current poster is read. If it is a **Quebec poster**, the script looks for one with the French title, otherwise the original title, among the first 30 posters Plex offers. When several are equally close, the script prefers the one Plex recommends, then the first in Plex's order.
- **Other posters are never touched.** A poster without text, or whose title cannot be read, is never picked, because it cannot be checked.
- If no suitable poster is found, the title is reported so you can do it by hand. A **locked** Quebec poster is reported, and only replaced with `--fix-locked-quebec`.
- Posters go through the same review page as logos (with a "Posters" filter), and share the same notifications, ignore list and undo.

## Logs

Each run creates a folder in `logs/` named after the date, time and mode: `simulation` for a dry run, `application` for a run with `--apply`.

```
logs/
└── 2026-09-23_18h20m05_simulation/
    ├── _summary.txt       ← per-library table and totals
    ├── Movies.txt         ← title-by-title details, then a summary
    ├── TV Shows.txt
    ├── review.html        ← with --html
    └── undo.json          ← with --apply
```

Each file starts with a header (date, mode, rules, legend) and ends with a summary (duration, counts, and the titles concerned). In the details, each title ends with a tag:

| Tag | Meaning |
|---|---|
| `[TO ADD]` / `[ADDED]` | No logo yet: one will be / was set |
| `[TO REPLACE]` / `[REPLACED]` | The current image (logo or poster) will be / was replaced (Quebec, or `--replace`) |
| `[OK]` | Already the right logo (only with `--replace`) |
| `[KEPT]` | A logo is already set: left alone |
| `[LOCKED]` | Hand-picked image (locked field): left alone |
| `[NONE]` | Plex recommends no logo in any language: pick one by hand |
| `[CHECK]` | Quebec image, and no suitable replacement found: do it by hand |
| `[REJECTED]` | With `--choices`: rejected in the review page |
| `[RECHECK]` | With `--choices`: the planned image changed since the dry run |
| `[NOT REVIEWED]` | With `--choices`: not in the choices file (new since the dry run) |
| `[IGNORED]` | On the ignore list |
| `[ERROR]` | Error (the message follows) |

A title without a logo, set from the English recommendation:

```
[1/3] BNA (2020)
  Current logo     : none
  Plex search      : French: none | English: found
  Recommended logo : English, 618x239 px
  Found on Plex    : candidate #3 of 7 (tmdb), same URL
  ==> [TO ADD] English logo 618x239 px
```

A Quebec logo replaced:

```
[52/303] Bullet Train (2022)
  Current logo     : #8 of 18 (tmdb), set automatically by Plex
  Titles           : France "Bullet Train" | Quebec "Train à grande vitesse" | original "Bullet Train"
  Logo reads       : "TRAIN A C GRANDE VITESSE" -> Quebec
  Plex search      : French: found
  Recommended reads: "TRAIN A C GRANDE VITESSE" -> Quebec
  OCR choice       : candidate #4 of 18 (tmdb), "BULLET TRAIT" -> French
  ==> [TO REPLACE] logo "BULLET TRAIT" (French), instead of #8 (Quebec)
```

The OCR does not always read perfectly ("TRAIT" instead of "TRAIN"), but the comparison tolerates such small errors.

## Troubleshooting

| Problem | Solution |
|---|---|
| `Permission denied` when running `./install.sh` | Run `bash install.sh` instead. |
| `Python 3.8 or later is required` | Install a newer Python, or run `PYTHON=python3.11 ./install.sh` if several versions are installed. |
| `No module named ...` | Run the script with `.venv/bin/python`, not `python3`. |
| The installer stops with `The dependencies do not load correctly` | Delete the `.venv` folder and run `./install.sh` again. If it persists, open an issue with the full output. |
| `Plex token rejected` | Your token changed: `.venv/bin/python configure.py --token`. |
| `Cannot connect to the Plex server` | Check the address and port. From the machine, `curl http://address:32400/identity` should answer. |
| `Libraries not found` | The names must match Plex exactly: `.venv/bin/python configure.py --libraries`. |
| A new title is not processed by the Tautulli hook | Check that its library is in `PLEX_LIBRARIES`, and read `logs/tautulli.log`. With Tautulli in a container, run `configure.py --tautulli`. |

## Good to know

- An image selected by the script becomes **locked**, like a manual choice: Plex will not replace it on refresh, and later runs leave it alone.
- Nothing is deleted: the previous logo or poster stays available in Plex (*Edit > Logo* or *Poster*).
- Only the main movie or show images are handled, not those of seasons or episodes.
- The installer replaces OpenCV 5, pulled in by the OCR engine, with an older build, because OpenCV 5 crashes on import on some machines.
- `config.env`, `ignored.json`, `logs/`, `.venv/` and `.cache-ocr.json` must not be published (they are in `.gitignore`): they contain your token or the list of your titles.

## Tests

The tests are built from real cases (*Edge of Tomorrow*, *Bullet Train*, *The Banker*, *Captain America*, *Avatar*…). They cover the Quebec detection, posters, notifications, the ignore list and the setup wizard, and run without a Plex server or the OCR engine:

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

GitHub Actions runs them on every push (Python 3.8 and 3.12).

## Credits

- Inspired by [relkai/plex-bulk-logo-updater](https://github.com/relkai/plex-bulk-logo-updater).
- Developed with the help of an AI assistant (Claude), then reviewed and tested on a real Plex library.

## License

MIT, see [LICENSE](LICENSE).
