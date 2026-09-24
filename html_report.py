"""
Review page (review.html): a single self-contained file with embedded images,
no link to the Plex server and no token. Open it in a browser, approve or
reject each change, then export choices.json for --choices.
The page itself is in French, like the rest of the user-facing messages.
"""
import base64
import html
import io
import json
import time

CHOICES_FORMAT = "plex-smart-logo-updater/choices-v1"
# Formats accepted by --choices
# Older formats are still accepted
CHOICES_FORMATS = (CHOICES_FORMAT, "plex-logo-fr/choices-v1", "plex-logo-fr/choix-v1")
THUMB_SIZE = (480, 150)


def thumbnail(img):
    """WebP thumbnail as a data URI."""
    img = img.copy()
    img.thumbnail(THUMB_SIZE)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=80)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def card(library, item, label, plan, current_thumb, new_thumb, decidable, category_label, mention_label):
    fr, ca, en = plan.titles
    return {
        "id": str(item.ratingKey),
        "library": library,
        "title": label,
        "category": plan.category,
        "categoryLabel": category_label,
        "mention": plan.mention,
        "mentionLabel": mention_label,
        "quebec": bool(plan.current_is_qc),
        "detail": plan.detail,
        "fr": fr, "ca": ca, "en": en,
        "target": plan.target_id if decidable else None,
        "before": current_thumb,
        "after": new_thumb,
        "decidable": decidable,
    }


def write(path, run_dir, apply, cards):
    data = {
        "format": CHOICES_FORMAT,
        "simulation": run_dir,
        "apply": apply,
        "generated": time.strftime("%d/%m/%Y à %H:%M"),
        "cards": cards,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", payload).replace("__TITLE__", html.escape(run_dir))
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contrôle des logos</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --text: #1d2330; --muted: #5f6878; --line: #dde1e7;
  --ok: #1f8a4c; --ok-bg: #e5f5ec; --no: #c23b32; --no-bg: #fbe9e7;
  --accent: #2f5fd0; --warn: #a86400; --warn-bg: #fff3dc; --qc: #7a3fc4; --qc-bg: #f1e9fb;
  --logo-bg: #2b2f36;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c; --panel: #1d2128; --text: #e7eaf0; --muted: #9aa3b2; --line: #2e343d;
    --ok: #4cc27f; --ok-bg: #173826; --no: #f07268; --no-bg: #40201e;
    --accent: #7ea2ff; --warn: #f0b04a; --warn-bg: #3a2c12; --qc: #b98cf2; --qc-bg: #2d2140;
    --logo-bg: #2b2f36;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; padding-bottom: 90px; }
header { padding: 24px 16px 8px; max-width: 1200px; margin: 0 auto; }
h1 { font-size: 22px; margin: 0 0 4px; }
.sub { color: var(--muted); font-size: 13px; }
.steps { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; margin: 14px 0 0; }
.steps ol { margin: 6px 0 0; padding-left: 20px; }
.steps code { background: var(--bg); padding: 1px 5px; border-radius: 4px; font-size: 13px; word-break: break-all; }
.toolbar { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line); }
.toolbar-in { max-width: 1200px; margin: 0 auto; padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.chip { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 999px;
  padding: 5px 11px; font-size: 13px; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: #fff; }
.chip .n { opacity: .75; margin-left: 4px; }
input[type=search], select { background: var(--panel); color: var(--text); border: 1px solid var(--line);
  border-radius: 8px; padding: 6px 10px; font-size: 13px; }
input[type=search] { flex: 1 1 180px; min-width: 0; }
main { max-width: 1200px; margin: 0 auto; padding: 12px 16px; display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 12px;
  display: flex; flex-direction: column; gap: 8px; border-left: 4px solid var(--line); }
.card.ok { border-left-color: var(--ok); }
.card.no { border-left-color: var(--no); opacity: .72; }
.card.info { border-left-color: var(--warn); }
.card h2 { font-size: 15px; margin: 0; }
.lib { color: var(--muted); font-size: 12px; }
.badges { display: flex; flex-wrap: wrap; gap: 5px; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 5px; background: var(--bg); color: var(--muted); }
.badge.qc { background: var(--qc-bg); color: var(--qc); }
.badge.warn { background: var(--warn-bg); color: var(--warn); }
.logos { display: grid; grid-template-columns: 1fr auto 1fr; gap: 6px; align-items: center; }
.logo { background: var(--logo-bg); border-radius: 8px; height: 96px; display: flex; align-items: center;
  justify-content: center; padding: 6px; position: relative; }
body.bg-light .logo { background: #e9ecf0; }
body.bg-check .logo { background: repeating-conic-gradient(#8a8f98 0% 25%, #b9bdc4 0% 50%) 50% / 16px 16px; }
.logo img { max-width: 100%; max-height: 100%; object-fit: contain; }
.logo .cap { position: absolute; top: 4px; left: 6px; font-size: 10px; color: #cfd4dc; text-transform: uppercase; letter-spacing: .05em; }
body.bg-light .logo .cap { color: #5f6878; }
.logo .none { color: #9aa3b2; font-size: 12px; }
.arrow { color: var(--muted); }
.titles { font-size: 12px; color: var(--muted); }
.titles b { color: var(--text); font-weight: 600; }
.detail { font-size: 12px; color: var(--muted); }
.actions { display: flex; gap: 6px; margin-top: auto; }
.actions button { flex: 1; border-radius: 8px; padding: 7px; font-size: 14px; font-weight: 600; cursor: pointer;
  border: 1px solid var(--line); background: var(--panel); color: var(--text); }
.actions button.sel-ok { background: var(--ok-bg); border-color: var(--ok); color: var(--ok); }
.actions button.sel-no { background: var(--no-bg); border-color: var(--no); color: var(--no); }
.infonote { font-size: 12px; color: var(--warn); }
footer { position: fixed; bottom: 0; left: 0; right: 0; background: var(--panel); border-top: 1px solid var(--line); z-index: 6; }
.foot-in { max-width: 1200px; margin: 0 auto; padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.counts { flex: 1 1 200px; font-size: 14px; }
.counts .o { color: var(--ok); font-weight: 700; } .counts .x { color: var(--no); font-weight: 700; }
.btn { border-radius: 8px; padding: 8px 14px; font-weight: 600; cursor: pointer; border: 1px solid var(--line);
  background: var(--panel); color: var(--text); font-size: 14px; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.empty { grid-column: 1 / -1; text-align: center; color: var(--muted); padding: 40px 0; }
@media (max-width: 420px) { main { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <h1>Contrôle des logos Plex</h1>
  <div class="sub" id="sub"></div>
  <div class="steps" id="steps"></div>
</header>
<div class="toolbar"><div class="toolbar-in" id="toolbar"></div></div>
<main id="grid"></main>
<footer id="footer"><div class="foot-in">
  <div class="counts" id="counts"></div>
  <button class="btn" id="all-ok">Tout valider (filtre)</button>
  <button class="btn" id="all-no">Tout refuser (filtre)</button>
  <button class="btn primary" id="export">Exporter choices.json</button>
</div></footer>
<script type="application/json" id="data">__DATA__</script>
<script>
(function () {
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const cards = DATA.cards;
  const decidable = cards.filter(c => c.decidable);
  const storeKey = "plex-smart-logo-updater:" + DATA.simulation;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storeKey) || "{}"); } catch (e) { saved = {}; }
  const decisions = {};
  decidable.forEach(c => { decisions[c.id] = saved[c.id] === false ? false : true; });
  function persist() { try { localStorage.setItem(storeKey, JSON.stringify(decisions)); } catch (e) {} }

  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));

  // En-tête
  document.getElementById("sub").textContent =
    (DATA.apply ? "Application" : "Simulation") + " du " + DATA.generated + " — " + DATA.simulation;
  const steps = document.getElementById("steps");
  if (DATA.apply) {
    steps.innerHTML = "<b>Page de consultation :</b> ces changements ont déjà été appliqués à Plex. " +
      "Pour les annuler : <code>plex-smart-logo-updater.py --undo logs/" + esc(DATA.simulation) + " --apply</code>";
    document.getElementById("footer").style.display = "none";
    document.body.style.paddingBottom = "16px";
  } else {
    steps.innerHTML = "<b>Comment faire :</b><ol>" +
      "<li>Regarde chaque changement. Tout est <b>validé</b> par défaut : clique sur <b>Refuser</b> pour ceux que tu ne veux pas. Les filtres aident à commencer par les cas douteux (<b>Non vérifié</b>).</li>" +
      "<li>Clique sur <b>Exporter choices.json</b> (en bas).</li>" +
      "<li>Copie <code>choices.json</code> sur la seedbox, dans <code>logs/" + esc(DATA.simulation) + "/</code>.</li>" +
      "<li>Lance : <code>plex-smart-logo-updater.py --apply --choices logs/" + esc(DATA.simulation) + "/choices.json</code></li></ol>" +
      "Tes choix sont gardés dans ce navigateur si tu fermes la page.";
  }

  // Filtres
  const FILTERS = [
    ["all", "Tout", c => true],
    ["unverified", "Non vérifié", c => c.mention === "unverified"],
    ["quebec", "Québécois remplacé", c => c.quebec && c.decidable],
    ["original", "Titre original", c => c.mention === "original"],
    ["inferred", "Français déduit", c => c.mention === "inferred"],
    ["add", "Ajouts", c => c.category === "add"],
    ["replace", "Remplacements", c => c.category === "replace"],
    ["refused", "Refusés", c => c.decidable && decisions[c.id] === false],
    ["info", "À faire à la main", c => !c.decidable],
  ];
  let filter = "all", query = "", library = "", bg = "dark";
  const toolbar = document.getElementById("toolbar");
  function renderToolbar() {
    const libs = [...new Set(cards.map(c => c.library))];
    toolbar.innerHTML = FILTERS.map(([k, label, fn]) => {
      const n = cards.filter(fn).length;
      if (!n && k !== "all") return "";
      if (DATA.apply && k === "refused") return "";
      return `<button class="chip" data-f="${k}" aria-pressed="${filter === k}">${label}<span class="n">${n}</span></button>`;
    }).join("") +
      `<input type="search" id="q" placeholder="Rechercher un titre…" value="${esc(query)}">` +
      (libs.length > 1 ? `<select id="lib"><option value="">Toutes les bibliothèques</option>` +
        libs.map(l => `<option ${l === library ? "selected" : ""}>${esc(l)}</option>`).join("") + `</select>` : "") +
      `<select id="bg" title="Fond des logos"><option value="dark">Fond sombre</option><option value="light">Fond clair</option><option value="check">Damier</option></select>`;
    toolbar.querySelectorAll(".chip").forEach(b => b.onclick = () => { filter = b.dataset.f; renderToolbar(); renderGrid(); });
    const q = toolbar.querySelector("#q");
    q.oninput = () => { query = q.value.toLowerCase(); renderGrid(); };
    const lib = toolbar.querySelector("#lib");
    if (lib) lib.onchange = () => { library = lib.value; renderGrid(); };
    const bgSel = toolbar.querySelector("#bg");
    bgSel.value = bg;
    bgSel.onchange = () => { bg = bgSel.value; document.body.className = bg === "dark" ? "" : "bg-" + bg; };
  }

  function visible() {
    const fn = FILTERS.find(f => f[0] === filter)[2];
    return cards.filter(c => fn(c) && (!library || c.library === library) &&
      (!query || c.title.toLowerCase().includes(query)));
  }

  function logoBox(src, cap, emptyText) {
    return `<div class="logo"><span class="cap">${cap}</span>` +
      (src ? `<img src="${src}" alt="">` : `<span class="none">${emptyText}</span>`) + `</div>`;
  }

  function cardHtml(c) {
    const state = !c.decidable ? "info" : (decisions[c.id] ? "ok" : "no");
    const badges = [`<span class="badge">${esc(c.categoryLabel)}</span>`];
    if (c.quebec) badges.push(`<span class="badge qc">Logo actuel québécois</span>`);
    if (c.mention) badges.push(`<span class="badge warn">${esc(c.mentionLabel)}</span>`);
    const titles = c.fr ? `<div class="titles">France <b>${esc(c.fr)}</b> · Québec <b>${esc(c.ca)}</b>` +
      (c.en ? ` · original <b>${esc(c.en)}</b>` : "") + `</div>` : "";
    const actions = c.decidable && !DATA.apply ?
      `<div class="actions"><button data-id="${c.id}" data-v="1" class="${decisions[c.id] ? "sel-ok" : ""}">✓ Valider</button>` +
      `<button data-id="${c.id}" data-v="0" class="${decisions[c.id] ? "" : "sel-no"}">✗ Refuser</button></div>` :
      (!c.decidable ? `<div class="infonote">Rien ne sera modifié : à faire à la main dans Plex.</div>` : "");
    return `<article class="card ${state}"><div><h2>${esc(c.title)}</h2><div class="lib">${esc(c.library)}</div></div>` +
      `<div class="badges">${badges.join("")}</div>` +
      `<div class="logos">${logoBox(c.before, "avant", "aucun logo")}<span class="arrow">→</span>` +
      `${logoBox(c.after, "après", c.decidable ? "image indisponible" : "aucun changement")}</div>` +
      titles + `<div class="detail">${esc(c.detail)}</div>` + actions + `</article>`;
  }

  const grid = document.getElementById("grid");
  function renderGrid() {
    const list = visible();
    grid.innerHTML = list.length ? list.map(cardHtml).join("") : `<div class="empty">Aucun titre pour ce filtre.</div>`;
    grid.querySelectorAll(".actions button").forEach(b => b.onclick = () => {
      decisions[b.dataset.id] = b.dataset.v === "1"; persist(); renderGrid(); renderCounts();
      if (filter === "refused") renderToolbar();
    });
    renderCounts();
  }

  function renderCounts() {
    const ok = decidable.filter(c => decisions[c.id]).length;
    document.getElementById("counts").innerHTML =
      `<span class="o">${ok}</span> validé(s) · <span class="x">${decidable.length - ok}</span> refusé(s) sur ${decidable.length}`;
  }

  function setAll(v) {
    visible().filter(c => c.decidable).forEach(c => { decisions[c.id] = v; });
    persist(); renderToolbar(); renderGrid();
  }
  document.getElementById("all-ok").onclick = () => setAll(true);
  document.getElementById("all-no").onclick = () => setAll(false);

  document.getElementById("export").onclick = () => {
    const out = { format: DATA.format, simulation: DATA.simulation, exported: new Date().toISOString(), decisions: {} };
    decidable.forEach(c => { out.decisions[c.id] = { ok: decisions[c.id], target: c.target, title: c.title, library: c.library }; });
    const blob = new Blob([JSON.stringify(out, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = "choices.json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  renderToolbar();
  renderGrid();
})();
</script>
</body>
</html>
"""
