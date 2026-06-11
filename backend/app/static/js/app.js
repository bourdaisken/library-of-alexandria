/* Library of Alexandria — PWA frontend. */
const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const r = await fetch(path, opts);
  if (r.status === 401) showLogin();
  let data = null;
  try { data = await r.json(); } catch (_) {}
  return { ok: r.ok, status: r.status, data };
};
const status = (el, msg, kind) => { el.className = "status " + (kind || "info"); el.textContent = msg; el.classList.remove("hidden"); };
const loadScript = (src) => new Promise((res, rej) => {
  const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s);
});
const tsClient = () => { const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())}.${p(d.getHours())}.${p(d.getMinutes())}`; };

let dest = "library", currentUser = null, currentRun = null;
let libMode = "grid", reviewOnly = false;
let selectMode = false; const selectedIds = new Set();
let editingWorkId = null, editingEditionId = null, editingCopyId = null;
let buyingWishlistId = null;   // set when moving a wishlist item into the library

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    t.classList.add("active");
    document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
    $("view-" + t.dataset.view).classList.remove("hidden");
    if (t.dataset.view === "library") showLibrary();
    if (t.dataset.view === "wishlist") loadWishlist();
    if (t.dataset.view === "admin") loadAdmin();
    if (t.dataset.view === "detail") renderDetail();
    if (t.dataset.view === "collections") loadCollectionsTab();
    if (t.dataset.view === "stats") { loadDashboard(); loadDataDictionary(); }
    if (t.dataset.view === "enrich") loadDQ();
    if (t.dataset.view === "metadata") openMetadataTab();
  })
);

// ---------- skins ----------
let _skins = null;
function currentSkin() { return document.documentElement.getAttribute("data-theme") || "cupertino"; }
function applySkin(id, persist) {
  document.documentElement.setAttribute("data-theme", id);
  try { localStorage.setItem("loa-skin", id); } catch (e) {}
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) { const bg = getComputedStyle(document.body).backgroundColor; if (bg) meta.setAttribute("content", bg); }
  // Propagate to the embedded BookRen tab if it's already loaded (same-origin).
  try {
    const f = $("bookren-frame");
    if (f && f.contentDocument) f.contentDocument.documentElement.setAttribute("data-theme", id);
  } catch (e) {}
  if (persist) api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skin: id }) });
}
async function loadSkinPicker() {
  if (!_skins) { try { _skins = await (await fetch("/static/skins.json")).json(); } catch (e) { _skins = []; } }
  const sel = $("skin-select"); sel.innerHTML = "";
  _skins.forEach((s) => sel.add(new Option(s.name, s.id)));
  sel.value = currentSkin();
  sel.onchange = () => applySkin(sel.value, true);
}
async function applyServerSkin() {
  // The admin-chosen skin (DB) is the shared default; apply it for everyone on login.
  const { ok, data } = await api("/api/settings");
  if (ok && data.skin) applySkin(data.skin, false);
}

// ---------- E-book Metadata Quality tab (embedded BookRen UI, lazy-loaded) ----------
function openMetadataTab() {
  const f = $("bookren-frame");
  if (!f.getAttribute("src")) f.setAttribute("src", "/bookren");
}

// ---------- reusable server-side folder picker ----------
let _fpPick = null, _fpPath = null;
async function _fpLoad(path) {
  const { ok, data } = await api("/api/browse", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: path || null }),
  });
  if (!ok) return;
  _fpPath = data.path;
  $("fp-cur").textContent = data.path || "(choose a starting location)";
  $("fp-up").disabled = !data.parent;
  $("fp-up").dataset.path = data.parent || "";
  $("fp-use").disabled = !data.path;
  const body = $("fp-body"); body.innerHTML = "";
  const row = (label, cls, onClick) => {
    const d = document.createElement("div"); d.className = "fp-entry " + (cls || "");
    d.textContent = label; if (onClick) d.addEventListener("click", onClick); body.appendChild(d);
  };
  if (!data.path) (data.shortcuts || []).forEach((s) => row("📂 " + s.name, "", () => _fpLoad(s.path)));
  (data.dirs || []).forEach((dir) => row("📁 " + dir.name, "", () => _fpLoad(dir.path)));
  (data.files || []).forEach((f) => row("📄 " + f.name, "file"));
  if (data.path && !(data.dirs || []).length && !(data.files || []).length) row("(empty folder)", "file");
}
function openFolderPicker(onPick, startPath) {
  _fpPick = onPick;
  $("fp-overlay").classList.remove("hidden");
  _fpLoad(startPath || null);
}
$("fp-close").addEventListener("click", () => $("fp-overlay").classList.add("hidden"));
$("fp-up").addEventListener("click", (e) => _fpLoad(e.target.dataset.path || null));
$("fp-use").addEventListener("click", () => {
  $("fp-overlay").classList.add("hidden");
  if (_fpPick && _fpPath) _fpPick(_fpPath);
});

// ---------- Describe a book (LibraryThing TALPA discovery) ----------
function openDiscover() {
  $("discover-body").innerHTML = `<div class="muted" style="padding:10px">Describe the book and Search.</div>`;
  $("discover-foot").textContent = "LibraryThing TALPA · ~50 searches/day.";
  $("discover-overlay").classList.remove("hidden");
  $("discover-query").focus();
}
async function runDiscover() {
  const q = $("discover-query").value.trim();
  if (!q) return;
  $("discover-body").innerHTML = `<div class="muted" style="padding:10px">Thinking…</div>`;
  const { ok, data } = await api("/api/discover", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q }),
  });
  if (!ok) { $("discover-body").innerHTML = `<div class="muted" style="padding:10px">${data?.error || "Search failed."}</div>`; return; }
  const res = data.results || [];
  if (data.remaining != null) $("discover-foot").textContent = `LibraryThing TALPA · ${data.remaining} searches left today.`;
  if (!res.length) { $("discover-body").innerHTML = `<div class="muted" style="padding:10px">No matches. Try describing it differently.</div>`; return; }
  const body = $("discover-body"); body.innerHTML = "";
  res.forEach((c) => {
    const row = document.createElement("div"); row.className = "match-row";
    const thumb = c.isbn ? `https://covers.openlibrary.org/b/isbn/${c.isbn}-M.jpg?default=false` : "";
    row.innerHTML = `${thumb ? `<img class="match-cover" loading="lazy" src="${thumb}" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : `<div class="match-cover"></div>`}
      <div class="match-meta"><div class="mt"></div><div class="ma"></div></div>
      <button class="btn"></button>`;
    row.querySelector(".mt").textContent = c.title || "(untitled)";
    row.querySelector(".ma").textContent = c.isbn ? "ISBN " + c.isbn : (c.isbns && c.isbns.length ? c.isbns[0] : "");
    const btn = row.querySelector("button");
    if (c.owned_work_id) {
      btn.textContent = "✓ In library · View"; btn.classList.add("primary");
      btn.addEventListener("click", () => viewOwned(c.owned_work_id));
    } else {
      btn.textContent = "★ Add to wishlist";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        const r = await api("/api/wishlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: c.title, isbn: c.isbn }) });
        btn.textContent = r.ok ? "✓ Added" : "Failed"; if (!r.ok) btn.disabled = false;
      });
    }
    body.appendChild(row);
  });
}
async function viewOwned(workId) {
  const { ok, data } = await api(`/api/works/${workId}`);
  if (ok && data && data.id) { $("discover-overlay").classList.add("hidden"); openDetail(data); }
}
$("discover-btn").addEventListener("click", openDiscover);
$("discover-close").addEventListener("click", () => $("discover-overlay").classList.add("hidden"));
$("discover-search").addEventListener("click", runDiscover);
$("discover-query").addEventListener("keydown", (e) => { if (e.key === "Enter") runDiscover(); });

// ---------- BiblioNet match picker (no-ISBN books) ----------
let _matchEd = null, _matchSourcesLoaded = false;
const _matchDefault = new Set(["politeianet", "biblionet", "google", "loc"]);   // checked by default
async function loadMatchSources() {
  if (_matchSourcesLoaded) return;
  const { ok, data } = await api("/api/enrichment/match-sources");
  if (!ok) return;
  const box = $("match-sources"); box.innerHTML = "";
  (data.sources || []).forEach((s) => {
    const lbl = document.createElement("label"); lbl.className = "chk inline src";
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.value = s.key;
    cb.checked = _matchDefault.has(s.key);
    lbl.append(cb, document.createTextNode(" " + s.name));
    box.appendChild(lbl);
  });
  _matchSourcesLoaded = true;
}
function openMatchModal(w) {
  _matchEd = (w.editions || [])[0];
  if (!_matchEd) { alert("This book has no edition to match."); return; }
  $("match-query").value = w.title || "";
  $("match-body").innerHTML = `<div class="muted" style="padding:10px">Choose sources, then Search.</div>`;
  // Cover upload / camera is always available — add one, or replace a blank/wrong cover.
  $("match-cover-add").style.display = "";
  $("cover-add-status").textContent = "";
  $("match-overlay").classList.remove("hidden");
  loadMatchSources().then(runMatchSearch);
}
async function uploadMatchCover(file) {
  if (!file || !_matchEd) return;
  if (!file.type || !file.type.startsWith("image/")) { $("cover-add-status").textContent = "Please choose an image file."; return; }
  $("cover-add-status").textContent = "Uploading…";
  const fd = new FormData(); fd.append("file", file);
  const r = await fetch(`/api/editions/${_matchEd.id}/cover`, { method: "POST", body: fd });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data.ok) { $("cover-add-status").textContent = data.error || `Upload failed (HTTP ${r.status})`; return; }
  _matchEd.cover_path = data.cover_path;
  _coverBust[_matchEd.id] = Date.now();   // bust the cached image everywhere (grid + detail)
  $("cover-add-status").textContent = "Cover saved ✓";
  libDirty = true;
  // show it immediately in Detail
  const cover = $("detail-cover");
  if (cover) { cover.src = coverUrl(_matchEd); cover.style.display = ""; }
}
async function runMatchSearch() {
  const q = $("match-query").value.trim();
  if (!q) return;
  const sources = [...document.querySelectorAll("#match-sources input:checked")].map((c) => c.value);
  if (!sources.length) { $("match-body").innerHTML = `<div class="muted" style="padding:10px">Pick at least one source.</div>`; return; }
  $("match-body").innerHTML = `<div class="muted" style="padding:10px">Searching ${sources.join(", ")}…</div>`;
  const { ok, data } = await api("/api/enrichment/match-search", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: q, sources }),
  });
  if (!ok) { $("match-body").innerHTML = `<div class="muted" style="padding:10px">${data?.error || "Search failed."}</div>`; return; }
  const cands = data.candidates || [];
  if (!cands.length) { $("match-body").innerHTML = `<div class="muted" style="padding:10px">No results. Try fewer words (some sources match every word).</div>`; return; }
  const body = $("match-body"); body.innerHTML = "";
  cands.forEach((c) => {
    const row = document.createElement("div"); row.className = "match-row";
    const meta = [c.authors && c.authors.length ? c.authors.join(", ") : "", c.published_date || "", c.pages ? c.pages + " pp." : "", c.isbn ? "ISBN " + c.isbn : ""].filter(Boolean).join(" · ");
    row.innerHTML = `${c.cover_url ? `<img class="match-cover" loading="lazy" src="${c.cover_url}" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : `<div class="match-cover"></div>`}
      <div class="match-meta"><div class="mt"></div><div class="ma"></div></div>
      <button class="btn primary">Use this</button>`;
    const mt = row.querySelector(".mt");
    mt.textContent = c.title + (c.subtitle ? " — " + c.subtitle : "") + " ";
    const sb = document.createElement("span"); sb.className = "badge"; sb.textContent = c.source; mt.appendChild(sb);
    row.querySelector(".ma").textContent = meta;
    row.querySelector("button").addEventListener("click", () => useCandidate(c, row));
    body.appendChild(row);
  });
}
async function useCandidate(c, row) {
  const btn = row.querySelector("button"); btn.disabled = true; btn.textContent = "Applying…";
  const { ok, data } = await api("/api/enrichment/apply-match", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      edition_id: _matchEd.id, candidate: c,
      update_title: $("match-update-title").checked,
      add_author_forms: $("match-add-author").checked,
    }),
  });
  if (ok) {
    $("match-overlay").classList.add("hidden");
    libDirty = true; refreshDetail();
    const a = data.applied || [];
    alert(a.length ? `Applied: ${a.join(", ")}.` : "Nothing to fill — those fields were already set.");
  } else { btn.disabled = false; btn.textContent = "Use this"; alert(data?.error || "Failed"); }
}
$("match-close").addEventListener("click", () => $("match-overlay").classList.add("hidden"));
$("match-search").addEventListener("click", runMatchSearch);
$("match-query").addEventListener("keydown", (e) => { if (e.key === "Enter") runMatchSearch(); });
["cover-upload", "cover-camera"].forEach((id) => $(id).addEventListener("change", (e) => {
  const f = e.target.files && e.target.files[0]; e.target.value = ""; uploadMatchCover(f);
}));

// ---------- data-quality studio (under Enrich) ----------
let _dqFieldBuilt = false;
async function loadDQ() {
  await ensureFields();
  if (_dqFieldBuilt || !FIELDS) return;
  _dqFieldBuilt = true;
  // Skinned custom dropdown (native <select> popups ignore the skin → "blue").
  replaceWithDropdown("dq-field", fieldItems(FIELDS), FIELDS[0] && FIELDS[0].key);
}
async function dqReplace(field, from, to) {
  status($("dq-status"), "Applying across the library…", "info");
  const { ok, data } = await api("/api/dq/replace", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ field, from, to }) });
  if (ok) {
    status($("dq-status"), `✓ Merged ${data.merged} value(s) → “${data.to}”.`, "ok");
    libDirty = true;
    const { data: d2 } = await api(`/api/dq/values?field=${encodeURIComponent(field)}`);
    renderDQValues(field, d2?.values || []);
  } else status($("dq-status"), data?.error || "Failed", "error");
}
function renderDQValues(field, values) {
  const box = $("dq-results"); box.innerHTML = "";
  if (!values.length) { box.innerHTML = '<div class="hint-row">No values.</div>'; return; }
  const h = document.createElement("div"); h.className = "hint-row"; h.textContent = `${values.length} distinct value(s)`; box.appendChild(h);
  values.forEach((v) => {
    const r = document.createElement("div"); r.className = "item";
    r.innerHTML = `<div class="meta"><div class="t"></div></div><span class="badge"></span><button class="btn">Replace…</button>`;
    r.querySelector(".t").textContent = v.value;
    r.querySelector(".badge").textContent = v.count;
    r.querySelector("button").addEventListener("click", async () => {
      const to = prompt(`Change “${v.value}” to:`, v.value);
      if (to === null || !to.trim()) return;
      dqReplace(field, [v.value], to.trim());
    });
    box.appendChild(r);
  });
}
function renderDQClusters(field, clusters) {
  const box = $("dq-results"); box.innerHTML = "";
  if (!clusters.length) { box.innerHTML = '<div class="hint-row">No similar groups found.</div>'; return; }
  const h = document.createElement("div"); h.className = "hint-row"; h.textContent = `${clusters.length} group(s) of near-duplicates`; box.appendChild(h);
  clusters.forEach((cl) => {
    const card = document.createElement("div"); card.className = "item";
    card.innerHTML = `<div class="meta"><div class="a"></div>
      <div class="search-row" style="margin-top:.4rem"><input class="canon"><button class="btn primary">Merge all → this</button></div></div>`;
    card.querySelector(".a").textContent = cl.values.map((v) => `${v.value} (${v.count})`).join("   ·   ");
    card.querySelector(".canon").value = cl.suggested;
    card.querySelector("button").addEventListener("click", () => {
      const to = card.querySelector(".canon").value.trim(); if (!to) return;
      dqReplace(field, cl.values.map((v) => v.value), to);
    });
    box.appendChild(card);
  });
}
$("dq-values-btn").addEventListener("click", async () => {
  const field = $("dq-field").value; if (!field) return;
  status($("dq-status"), "Loading values…", "info");
  const { data } = await api(`/api/dq/values?field=${encodeURIComponent(field)}`);
  status($("dq-status"), `${(data?.values || []).length} distinct value(s).`, "ok");
  renderDQValues(field, data?.values || []);
});
$("dq-clusters-btn").addEventListener("click", async () => {
  const field = $("dq-field").value; if (!field) return;
  status($("dq-status"), "Finding similar groups…", "info");
  const { data } = await api(`/api/dq/clusters?field=${encodeURIComponent(field)}`);
  status($("dq-status"), `${(data?.clusters || []).length} group(s).`, "ok");
  renderDQClusters(field, data?.clusters || []);
});

// ---------- stats / valuation dashboard ----------
function barList(el, items) {
  el.innerHTML = "";
  const max = Math.max(1, ...items.map((i) => i.count));
  items.forEach((i) => {
    const r = document.createElement("div"); r.className = "barrow";
    r.innerHTML = `<span class="bl"></span><span class="bt"><span class="bf" style="width:${Math.round(i.count / max * 100)}%"></span></span><span class="bn">${i.count}</span>`;
    r.querySelector(".bl").textContent = i.label;
    el.appendChild(r);
  });
}
let _ddLoaded = false;
async function loadDataDictionary() {
  if (_ddLoaded) return;
  const wrap = $("dd-grid");
  const { ok, data } = await api("/api/stats/data-dictionary");
  if (!ok || !data || !data.rows) { wrap.innerHTML = `<div class="hint-row">Could not load the data dictionary.</div>`; return; }
  _ddLoaded = true;
  const cols = data.columns || [];
  const numCols = new Set(["rows", "populated", "missing", "fill_rate_%", "distinct_values"]);
  const wrapCols = new Set(["description", "label", "most_frequent_values"]);
  const table = document.createElement("table"); table.className = "dd-table";
  const thead = document.createElement("thead"); const htr = document.createElement("tr");
  cols.forEach((c) => { const th = document.createElement("th"); th.textContent = c.replace(/_/g, " "); htr.appendChild(th); });
  thead.appendChild(htr); table.appendChild(thead);
  const tb = document.createElement("tbody");
  (data.rows || []).forEach((r) => {
    const tr = document.createElement("tr");
    cols.forEach((c) => {
      const td = document.createElement("td");
      const v = r[c]; td.textContent = (v === null || v === undefined) ? "" : String(v);
      if (numCols.has(c)) td.className = "num"; else if (wrapCols.has(c)) td.className = "wrap";
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  table.appendChild(tb);
  wrap.innerHTML = ""; wrap.appendChild(table);
}
async function loadDashboard() {
  const { data: d } = await api("/api/dashboard"); if (!d) return;
  const t = d.totals; $("dash-totals").innerHTML = "";
  [["works", t.works], ["editions", t.editions], ["copies", t.copies], ["authors", t.authors], ["wishlist", t.wishlist], ["collections", t.collections]]
    .forEach(([l, n]) => { const c = document.createElement("div"); c.className = "dash-stat"; c.innerHTML = `<div class="n">${n}</div><div class="l"></div>`; c.querySelector(".l").textContent = l; $("dash-totals").appendChild(c); });
  $("dash-value").innerHTML = (d.list_value.map((v) => `Catalog (list) value: <b>${v.total} ${v.currency}</b>`).join("<br>") || "No list prices recorded.") + `<br>Valuation (sum of per-copy estimates): <b>${d.valuation_total}</b>`;
  barList($("dash-reading"), [{ label: "read", count: d.reading.read }, { label: "reading", count: d.reading.reading }, { label: "unread", count: d.reading.unread }]);
  barList($("dash-bd1"), [
    ...d.by_kind.map((x) => ({ label: "medium · " + x.label, count: x.count })),
    ...d.by_copy_type.map((x) => ({ label: "type · " + x.label, count: x.count })),
    ...d.by_condition.map((x) => ({ label: "condition · " + x.label, count: x.count })),
  ]);
  barList($("dash-genres"), d.top_genres);
  barList($("dash-pubs"), d.top_publishers);
  barList($("dash-decades"), d.decades);
  barList($("dash-areas"), d.by_area);
}

// ---------- collections helpers ----------
async function fetchCollections(kind) { const { data } = await api("/api/collections?kind=" + kind); return (data && data.collections) || []; }
async function createCollection(kind) {
  const name = prompt(`New ${kind} collection name:`); if (!name || !name.trim()) return null;
  const { ok, data } = await api("/api/collections", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), kind }) });
  if (!ok) { alert(data?.error || "Failed"); return null; }
  return { id: data.id, name: data.name };
}
function fillCollSelect(sel, cols, firstLabel) {
  const prev = sel.value; sel.innerHTML = "";
  if (firstLabel !== null) sel.add(new Option(firstLabel, ""));
  cols.forEach((c) => sel.add(new Option(`${c.name}${c.count != null ? ` (${c.count})` : ""}`, c.id)));
  if (prev) sel.value = prev;
}

// ---------- destination toggle ----------
function setDest(d) {
  dest = d; buyingWishlistId = null;
  document.querySelectorAll("#dest .seg-btn").forEach((x) => x.classList.toggle("active", x.dataset.dest === d));
  const lib = d === "library";
  $("copy-card").classList.toggle("hidden", !lib);
  $("wish-card").classList.toggle("hidden", lib);
  $("dest-hint").textContent = lib
    ? "A copy you own — recorded with location, condition, price paid…"
    : "A book you want — e.g. spotted in a shop. Saved to your wishlist.";
  if (!lib) populateWishCollections();
}
$("dest").addEventListener("click", (e) => { const b = e.target.closest(".seg-btn"); if (b) setDest(b.dataset.dest); });
async function populateWishCollections() {
  fillCollSelect($("wish_collection"), await fetchCollections("wishlist"), "(no collection)");
}

// ---------- barcode photo ----------
$("scan-photo-btn").addEventListener("click", () => $("photo-input").click());
$("photo-input").addEventListener("change", async () => {
  const file = $("photo-input").files[0]; if (!file) return;
  status($("status"), "Reading barcode from photo…", "info");
  const fd = new FormData(); fd.append("image", file);
  const { ok, data } = await api("/api/decode", { method: "POST", body: fd });
  if (ok && data.isbn) { $("isbn").value = data.isbn; runLookup(); }
  else status($("status"), data?.error || "No barcode found — retry with the barcode in focus.", "error");
  $("photo-input").value = "";
});

// (Live scan removed — the photo capture below uses the rear camera and is more reliable.)

// ---------- lookup ----------
$("lookup-btn").addEventListener("click", runLookup);
$("isbn").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runLookup(); } });
async function runLookup() {
  const isbn = $("isbn").value.trim();
  if (!isbn) { status($("status"), "Enter or scan an ISBN first.", "error"); return; }
  status($("status"), "Looking up…", "info");
  const { ok, data } = await api(`/api/lookup?isbn=${encodeURIComponent(isbn)}`);
  if (!ok) { status($("status"), data?.error || "Not found — fill the details by hand.", "error"); return; }
  fillDetails(data);
  status($("status"), `Found via ${data.source}. Review & save.`, "ok");
  checkDuplicate();
}
function fillDetails(meta) {
  if (meta.title) $("title").value = meta.title;
  if (meta.authors?.length) $("authors").value = meta.authors.join("\n");
  if (meta.publisher) $("publisher").value = meta.publisher;
  const yr = (meta.published_date || "").match(/\d{4}/); if (yr) $("year").value = yr[0];
  if (meta.pages) $("pages").value = meta.pages;
  if (meta.description) $("description").value = meta.description;
  if (meta.cover_url) { $("cover").src = meta.cover_url; $("cover-wrap").classList.remove("hidden"); }
}

// ---------- search by title / author (Add tab) ----------
$("ts-search-btn").addEventListener("click", runTitleSearch);
["ts-title", "ts-author"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); runTitleSearch(); } }));
async function runTitleSearch() {
  const t = $("ts-title").value.trim(), a = $("ts-author").value.trim();
  const query = [t, a].filter(Boolean).join(" ");
  const box = $("ts-results");
  if (!query) { box.innerHTML = `<div class="muted">Type a title (and optionally an author).</div>`; return; }
  box.innerHTML = `<div class="muted">Searching…</div>`;
  const sources = ["google", "openlibrary", "biblionet", "politeianet", "loc"];
  const { ok, data } = await api("/api/enrichment/match-search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, sources }) });
  if (!ok) { box.innerHTML = `<div class="muted">${data?.error || "Search failed."}</div>`; return; }
  const cands = data.candidates || [];
  if (!cands.length) { box.innerHTML = `<div class="muted">No results — try fewer words (some sources match every word).</div>`; return; }
  box.innerHTML = "";
  cands.forEach((c) => {
    const row = document.createElement("div"); row.className = "ts-row";
    row.innerHTML = `${c.cover_url ? `<img class="ts-cover" loading="lazy" src="${c.cover_url}" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">` : `<div class="ts-cover"></div>`}
      <div class="ts-meta"><div class="tt"></div><div class="ta"></div></div><button class="btn">Use</button>`;
    row.querySelector(".tt").textContent = c.title + (c.subtitle ? " — " + c.subtitle : "");
    row.querySelector(".ta").textContent = [(c.authors || []).join(", "), c.published_date || "", c.isbn ? "ISBN " + c.isbn : "", c.source].filter(Boolean).join(" · ");
    row.querySelector("button").addEventListener("click", () => applyCandidate(c));
    box.appendChild(row);
  });
}
function applyCandidate(c) {
  fillDetails({ title: c.title, authors: c.authors, publisher: c.publisher, published_date: c.published_date, pages: c.pages, description: c.description, cover_url: c.cover_url });
  if (c.isbn) $("isbn").value = c.isbn;
  $("ts-results").innerHTML = "";
  status($("status"), `Filled from ${c.source}. Review & save.`, "ok");
  checkDuplicate();
}

// ---------- duplicate detection ("do I already own this?") ----------
let _dupExists = false, _dupTitle = "";
function fileFmt(path) { const m = (path || "").match(/\.([a-z0-9]+)$/i); return m ? m[1].toUpperCase() : "OPEN"; }
async function checkDuplicate() {
  const isbn = $("isbn").value.trim(), title = $("title").value.trim();
  const author0 = ($("authors").value.split("\n")[0] || "").trim();
  _dupExists = false; _dupTitle = "";
  const banner = $("dup-banner");
  if (editingWorkId || (!isbn && !title)) { banner.classList.add("hidden"); return; }
  const p = new URLSearchParams(); if (isbn) p.set("isbn", isbn); if (title) p.set("title", title); if (author0) p.set("author", author0);
  const { ok, data } = await api(`/api/books/find?${p.toString()}`);
  if (!ok || !(data.matches || []).length) { banner.classList.add("hidden"); return; }
  const w = data.matches[0]; _dupExists = true; _dupTitle = w.title;
  const copies = w.editions.flatMap((e) => e.copies);
  const phys = copies.filter((c) => c.kind !== "ebook");
  const ebooks = copies.filter((c) => c.kind === "ebook" && c.file_ref);
  banner.classList.remove("hidden"); banner.innerHTML = "";
  const h = document.createElement("div"); h.className = "dup-h"; h.textContent = `⚠ You already own “${w.title}”`; banner.appendChild(h);
  const locLine = document.createElement("div");
  const locs = [...new Set(phys.map((c) => c.location || "no location"))];
  locLine.textContent = phys.length ? `${phys.length} cop${phys.length > 1 ? "ies" : "y"} — ${locs.join(", ")}` : "No physical copies recorded.";
  banner.appendChild(locLine);
  if (ebooks.length) {
    const eb = document.createElement("div"); eb.className = "dup-eb";
    eb.textContent = "📚 E-book: " + ebooks.map((c) => fileFmt(c.file_ref) + (c.location ? " @ " + c.location : "")).join(", ");
    banner.appendChild(eb);
  }
  const row = document.createElement("div"); row.className = "btn-row";
  const view = document.createElement("button"); view.className = "btn"; view.textContent = "View the book I own";
  view.addEventListener("click", () => openDetail(w)); row.appendChild(view);
  banner.appendChild(row);
  const hint = document.createElement("div"); hint.className = "muted"; hint.textContent = "Saving adds another copy (e.g. a duplicate, or a copy in a different location).";
  banner.appendChild(hint);
}
$("isbn").addEventListener("change", checkDuplicate);
$("title").addEventListener("change", checkDuplicate);

// ---------- save (add or edit) ----------
$("save-btn").addEventListener("click", save);
function commonPayload() {
  return {
    title: $("title").value.trim(),
    authors: $("authors").value.split("\n").map((s) => s.trim()).filter(Boolean),
    isbn: $("isbn").value.trim(), asin: $("asin").value.trim(),
    publisher: $("publisher").value.trim(), year: $("year").value.trim(),
    pages: $("pages").value.trim(), format: $("format").value.trim(),
    language: $("language").value.trim(), list_price: $("list_price").value.trim(),
    series: $("series").value.trim(), series_position: $("series_position").value.trim(),
    tags: $("tags").value.split(",").map((s) => s.trim()).filter(Boolean),
    description: $("description").value.trim(),
  };
}
function copyPayload() {
  return {
    kind: $("kind").value, copy_type: $("copy_type").value,
    condition: $("condition").value || null, condition_grade: $("condition_grade").value || null,
    location: $("location").value.trim(), signed: $("signed").checked,
    acquired_today: $("acquired_today").checked,
    acquisition_price: $("acquisition_price").value.trim(), notes: $("copy_notes").value.trim(),
  };
}
async function save() {
  const ss = $("save-status");
  if (!$("title").value.trim()) { status(ss, "Title is required.", "error"); return; }
  status(ss, "Saving…", "info");
  let res;
  if (editingWorkId) {
    const payload = commonPayload();
    payload.copy = copyPayload();
    payload.edition_id = editingEditionId; payload.copy_id = editingCopyId;
    res = await api(`/api/works/${editingWorkId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (res.ok) { status(ss, "✓ Saved changes.", "ok"); libDirty = true; cancelEdit(); return; }
  } else if (dest === "library") {
    if (_dupExists && !confirm(`You already own “${_dupTitle}”. Add another copy?`)) { status(ss, "Cancelled — no duplicate added.", null); return; }
    const payload = commonPayload(); payload.copy = copyPayload();
    res = await api("/api/books", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } else {
    res = await api("/api/wishlist", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: $("title").value.trim(),
        authors: $("authors").value.split("\n").map((s) => s.trim()).filter(Boolean),
        isbn: $("isbn").value.trim(), target_price: $("target_price").value.trim(),
        priority: $("priority").value.trim(), notes: $("wish_notes").value.trim(),
        collection_id: $("wish_collection").value || null }) });
  }
  if (res.ok) {
    libDirty = true;
    if (dest === "library" && buyingWishlistId) {
      await api(`/api/wishlist/${buyingWishlistId}`, { method: "DELETE" });
      status(ss, "✓ Moved from wishlist to your library.", "ok");
    } else {
      status(ss, dest === "library" ? "✓ Added to your library." : "★ Added to wishlist.", "ok");
    }
    resetForm();
  }
  else status(ss, res.data?.error || `Save failed (HTTP ${res.status})`, "error");
}
function resetForm() {
  ["isbn","asin","title","authors","publisher","year","pages","format","language","list_price",
   "series","series_position","tags","description","location","acquisition_price","copy_notes",
   "target_price","priority","wish_notes"].forEach((id) => { $(id).value = ""; });
  $("signed").checked = false; $("acquired_today").checked = false;
  $("cover-wrap").classList.add("hidden"); $("status").classList.add("hidden");
  ["ts-title", "ts-author"].forEach((id) => { $(id).value = ""; });
  $("ts-results").innerHTML = ""; $("dup-banner").classList.add("hidden"); _dupExists = false; _dupTitle = "";
  $("delete-cover-row").classList.add("hidden");
  buyingWishlistId = null;
}

// ---------- edit / delete ----------
function editBook(w) {
  editingWorkId = w.id;
  document.querySelector('.tab[data-view="add"]').click();
  $("edit-banner").classList.remove("hidden"); $("edit-title").textContent = w.title;
  $("dest-card").classList.add("hidden"); dest = "library";
  $("copy-card").classList.remove("hidden"); $("wish-card").classList.add("hidden");
  const ed = w.editions[0] || {}, cp = (ed.copies && ed.copies[0]) || {};
  editingEditionId = ed.id || null; editingCopyId = cp.id || null;
  $("title").value = w.title || ""; $("authors").value = (w.authors || []).join("\n");
  $("series").value = w.series || ""; $("series_position").value = w.series_position || "";
  $("tags").value = (w.tags || []).join(", ");
  $("isbn").value = ed.isbn13 || ed.isbn10 || ""; $("publisher").value = ed.publisher || "";
  $("year").value = ed.year || ""; $("pages").value = ed.pages || ""; $("format").value = ed.format || "";
  $("language").value = ed.language || ""; $("list_price").value = ed.list_price || ""; $("description").value = ed.description || "";
  $("kind").value = cp.kind || "physical"; $("copy_type").value = cp.copy_type || "reading";
  $("condition").value = cp.condition || ""; $("condition_grade").value = cp.condition_grade || "";
  $("location").value = cp.location || ""; $("signed").checked = !!cp.signed; $("copy_notes").value = cp.notes || "";
  // Preview the current cover + offer to delete it.
  const cu = coverUrl(ed);
  if (cu) { $("cover").src = cu; $("cover-wrap").classList.remove("hidden"); } else { $("cover-wrap").classList.add("hidden"); }
  $("delete-cover-row").classList.toggle("hidden", !ed.cover_path);
  window.scrollTo(0, 0);
}
$("delete-cover-btn").addEventListener("click", async () => {
  if (!editingEditionId) return;
  if (!confirm("Delete this book's cover?")) return;
  const { ok, data } = await api(`/api/editions/${editingEditionId}/cover`, { method: "DELETE" });
  if (!ok) { status($("save-status"), data?.error || "Failed to delete cover.", "error"); return; }
  $("cover-wrap").classList.add("hidden"); $("cover").removeAttribute("src");
  $("delete-cover-row").classList.add("hidden");
  _coverBust[editingEditionId] = Date.now(); libDirty = true;
  status($("save-status"), "✓ Cover deleted.", "ok");
});
$("edit-cancel").addEventListener("click", cancelEdit);
function cancelEdit() {
  editingWorkId = editingEditionId = editingCopyId = null;
  $("edit-banner").classList.add("hidden"); $("dest-card").classList.remove("hidden");
  resetForm();
}
async function deleteBook(w) {
  if (!confirm(`Delete “${w.title}” and all its copies?\n\nThis cannot be undone.`)) return false;
  const { ok, data } = await api(`/api/works/${w.id}`, { method: "DELETE" });
  if (!ok) { alert(data?.error || "Delete failed"); return false; }
  libDirty = true;
  if (!$("view-detail").classList.contains("hidden")) document.querySelector('.tab[data-view="library"]').click();
  else loadLibrary();
  return true;
}

// ---------- library browse ----------
let searchTimer = null;
$("search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadLibrary(true), 250); });
$("viewmode").addEventListener("click", (e) => {
  const b = e.target.closest(".seg-btn"); if (!b) return;
  libMode = b.dataset.mode;
  document.querySelectorAll("#viewmode .seg-btn").forEach((x) => x.classList.toggle("active", x === b));
  renderLibrary(lastWorks);   // re-render everything already loaded in the new mode
});
$("review-only").addEventListener("change", (e) => { reviewOnly = e.target.checked; loadLibrary(true); });

// ----- model-driven filter / sort / search-field menus -----
let FIELDS = null, FIELD_OPS = null;

// Human-readable operator names (values stay as the API keys).
const OP_LABELS = {
  contains: "Contains", equals: "Equals", not_equals: "Does not equal",
  empty: "Is empty", not_empty: "Is not empty",
  gt: "Greater than", lt: "Less than", gte: "At least (≥)", lte: "At most (≤)",
  after: "After", before: "Before", true: "Yes", false: "No",
};
const opLabel = (o) => OP_LABELS[o] || (o.charAt(0).toUpperCase() + o.slice(1));
const noVal = (o) => ["empty", "not_empty", "true", "false"].includes(o);
function fillOps(sel, type, keep) {
  sel.innerHTML = "";
  (FIELD_OPS[type] || []).forEach((o) => sel.add(new Option(opLabel(o), o)));
  if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

// Custom dropdown: shows a friendly label + greyed, truncated example values per item.
// Exposes `.value` (get/set) and fires onChange; given an id it stands in for the <select>.
// Close any open dropdown and return its menu to its owner (so a clipped/scrolled
// ancestor never strands it in <body>).
function closeFdrops() {
  document.querySelectorAll(".fdrop.open").forEach((d) => {
    d.classList.remove("open");
    const mn = d._menu;
    if (mn) { mn.classList.add("hidden"); d.appendChild(mn); mn.style.cssText = ""; }
  });
}
document.addEventListener("click", closeFdrops);
window.addEventListener("resize", closeFdrops);
window.addEventListener("scroll", (e) => {   // the menu is portaled+fixed → close on page scroll…
  const open = document.querySelector(".fdrop.open");
  if (open && open._menu === e.target) return;   // …but not when scrolling inside the menu itself
  closeFdrops();
}, true);
// Portal a dropdown's menu to <body> and position it directly under its button. Set
// min-width to the button width FIRST (overriding the CSS min-width:100%, which would
// otherwise resolve to the full viewport at body level and throw off the measurement),
// then measure and flip left if it would overflow the right edge.
function openMenuUnder(wrap, btn, menu) {
  const r = btn.getBoundingClientRect();
  document.body.appendChild(menu);
  menu.style.cssText = `position:fixed; top:${r.bottom + 4}px; left:${r.left}px; min-width:${r.width}px;`;
  menu.classList.remove("hidden");
  const mw = menu.offsetWidth;
  if (r.left + mw + 8 > window.innerWidth) menu.style.left = Math.max(8, window.innerWidth - mw - 8) + "px";
  wrap.classList.add("open");
}
function fieldDropdown({ id, items, value, onChange }) {
  const wrap = document.createElement("div"); wrap.className = "fdrop"; if (id) wrap.id = id;
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "fdrop-btn";
  const menu = document.createElement("div"); menu.className = "fdrop-menu hidden";
  wrap._menu = menu;
  let cur = value !== undefined ? value : (items[0] && items[0].value);
  const itemOf = (v) => items.find((i) => i.value === v) || {};
  const sync = () => { btn.textContent = itemOf(cur).label || "—"; btn.title = itemOf(cur).help || ""; };
  let lastGroup = null;
  items.forEach((it) => {
    if (it.group && it.group !== lastGroup) {
      lastGroup = it.group;
      const g = document.createElement("div"); g.className = "fdrop-grp"; g.textContent = it.group; menu.appendChild(g);
    }
    const opt = document.createElement("div"); opt.className = "fdrop-opt"; if (it.help) opt.title = it.help;
    const lb = document.createElement("span"); lb.className = "fdrop-lb"; lb.textContent = it.label; opt.appendChild(lb);
    if (it.examples) { const ex = document.createElement("span"); ex.className = "fdrop-ex"; ex.textContent = "e.g. " + it.examples; opt.appendChild(ex); }
    opt.addEventListener("click", () => { cur = it.value; sync(); closeFdrops(); if (onChange) onChange(cur); });
    menu.appendChild(opt);
  });
  menu.addEventListener("click", (e) => e.stopPropagation());   // clicks inside the menu don't close it
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = wrap.classList.contains("open"); closeFdrops();
    if (!open) openMenuUnder(wrap, btn, menu);   // portal under the button (escapes clip-path ancestors)
  });
  Object.defineProperty(wrap, "value", { get: () => cur, set: (v) => { cur = v; sync(); }, configurable: true });
  wrap.append(btn, menu); sync(); return wrap;
}

// Build grouped dropdown items from FIELDS (optionally a leading blank/"default" entry).
function fieldItems(list, blank) {
  const items = blank ? [{ value: "", label: blank }] : [];
  list.forEach((f) => items.push({
    value: f.key, label: f.label, group: f.entity_label || "", help: f.help, examples: f.examples,
  }));
  return items;
}
function replaceWithDropdown(id, items, value, onChange) {
  const old = $(id); if (!old) return;
  const d = fieldDropdown({ id, items, value, onChange });
  old.replaceWith(d); return d;
}

// Auto-skin EVERY native <select> app-wide: their option popups are OS-rendered and ignore
// the skin (white). We KEEP the native <select> as the hidden source of truth (so existing
// code that reads/sets .value, listens for "change", or repopulates <option>s keeps working)
// and mirror it with a skinned, portaled dropdown. These ids become rich fieldDropdowns instead:
const _NO_SKIN = new Set(["search-field", "sort-field", "sort-dir", "dq-field"]);
const _NATIVE_VALUE = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
function skinSelect(sel) {
  if (!sel || sel.tagName !== "SELECT" || sel._skinned || _NO_SKIN.has(sel.id)) return;
  sel._skinned = true;
  const wrap = document.createElement("div"); wrap.className = "fdrop nsel";
  const btn = document.createElement("button"); btn.type = "button"; btn.className = "fdrop-btn";
  const menu = document.createElement("div"); menu.className = "fdrop-menu hidden";
  wrap._menu = menu;
  sel.parentNode.insertBefore(wrap, sel);
  wrap.append(sel, btn, menu); sel.classList.add("nsel-native");
  const syncLabel = () => {
    const o = sel.options[sel.selectedIndex];
    btn.textContent = (o && o.textContent.trim()) || "—";
    btn.disabled = sel.disabled;
    Array.from(menu.children).forEach((el, i) => el.classList.toggle("sel", i === sel.selectedIndex));
  };
  const rebuild = () => {
    menu.innerHTML = "";
    Array.from(sel.options).forEach((o) => {
      const opt = document.createElement("div"); opt.className = "fdrop-opt";
      const lb = document.createElement("span"); lb.className = "fdrop-lb"; lb.textContent = o.textContent;
      opt.appendChild(lb);
      opt.addEventListener("click", () => {
        if (sel.value !== o.value) { _NATIVE_VALUE.set.call(sel, o.value); sel.dispatchEvent(new Event("change", { bubbles: true })); }
        syncLabel(); closeFdrops();
      });
      menu.appendChild(opt);
    });
    syncLabel();
  };
  // intercept programmatic `sel.value = …` so the button label stays in sync
  Object.defineProperty(sel, "value", {
    configurable: true,
    get() { return _NATIVE_VALUE.get.call(sel); },
    set(v) { _NATIVE_VALUE.set.call(sel, v); syncLabel(); },
  });
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (sel.disabled) return;
    const open = wrap.classList.contains("open"); closeFdrops();
    if (!open) openMenuUnder(wrap, btn, menu);
  });
  menu.addEventListener("click", (e) => e.stopPropagation());
  new MutationObserver(rebuild).observe(sel, { childList: true, attributes: true, attributeFilter: ["disabled"] });
  rebuild();
}
function skinAllSelects(root) { (root || document).querySelectorAll("select").forEach(skinSelect); }
// Skin present selects + any added later (dynamically-built rows, modals, etc.).
new MutationObserver((muts) => {
  for (const mu of muts) for (const n of mu.addedNodes) {
    if (n.nodeType !== 1) continue;
    if (n.tagName === "SELECT") skinSelect(n);
    else if (n.querySelector && n.querySelector("select")) n.querySelectorAll("select").forEach(skinSelect);
  }
}).observe(document.documentElement, { childList: true, subtree: true });
skinAllSelects();

async function ensureFields() {
  if (FIELDS) return;
  const { data } = await api("/api/fields"); if (!data) return;
  FIELDS = data.fields; FIELD_OPS = data.ops;
  replaceWithDropdown("search-field", fieldItems(FIELDS.filter((f) => f.type === "text"), "All fields (keyword)"), "", () => loadLibrary(true));
  replaceWithDropdown("sort-field", fieldItems(FIELDS, "Title (default)"), "", () => loadLibrary(true));
  // sort direction as a skinned custom dropdown too (native <select> popups ignore the skin).
  replaceWithDropdown("sort-dir", [{ value: "asc", label: "Ascending" }, { value: "desc", label: "Descending" }], "asc", () => loadLibrary(true));
}
function addFilterRow() {
  if (!FIELDS) return;
  const row = document.createElement("div"); row.className = "search-row filter-row";
  const val = document.createElement("input"); val.placeholder = "value";
  const rm = document.createElement("button"); rm.className = "btn"; rm.textContent = "✕";
  const opSlot = document.createElement("div"); opSlot.className = "f-op-slot";
  let opDrop = null;
  function rebuildOps(type, keep) {
    const ops = (FIELD_OPS[type] || []).map((o) => ({ value: o, label: opLabel(o) }));
    const chosen = (keep && ops.some((o) => o.value === keep)) ? keep : (ops[0] && ops[0].value);
    opSlot.innerHTML = "";
    opDrop = fieldDropdown({ items: ops, value: chosen, onChange: () => { val.style.display = noVal(opDrop.value) ? "none" : ""; } });
    opDrop.classList.add("f-op");
    opSlot.appendChild(opDrop);
    val.style.display = noVal(opDrop.value) ? "none" : "";
  }
  const fs = fieldDropdown({
    items: fieldItems(FIELDS), value: FIELDS[0].key,
    onChange: (key) => rebuildOps((FIELDS.find((x) => x.key === key) || {}).type),
  });
  fs.classList.add("f-field");
  rm.addEventListener("click", () => { closeFdrops(); row.remove(); });
  row.append(fs, opSlot, val, rm); $("filter-rows").appendChild(row);
  rebuildOps((FIELDS.find((x) => x.key === fs.value) || {}).type);
}
function currentFilters() {
  return [...document.querySelectorAll("#filter-rows .filter-row")].map((r) => ({
    field: r.querySelector(".f-field").value,
    op: (r.querySelector(".f-op") || {}).value,
    value: r.querySelector("input").value,
  })).filter((f) => f.field && f.op);
}
$("toggle-filters").addEventListener("click", () => { ensureFields(); $("filter-panel").classList.toggle("hidden"); });
$("add-filter").addEventListener("click", addFilterRow);
$("apply-filters").addEventListener("click", () => loadLibrary(true));
$("clear-filters").addEventListener("click", () => { $("filter-rows").innerHTML = ""; $("sort-field").value = ""; $("search-field").value = ""; loadLibrary(true); });

const LIB_PAGE = 200;
let lastWorks = [], libOffset = 0, libTotal = null, libLoading = false, libSeq = 0, libDirty = true;

// Returning to the Library tab: re-render the already-loaded pages instantly (no refetch,
// no empty flash). Only fetch on first visit or after a change (libDirty).
function showLibrary() {
  if (lastWorks.length && !libDirty) {
    renderLibrary(lastWorks);
    $("lib-count").textContent = `showing ${lastWorks.length} of ${libTotal}`;
  } else {
    loadLibrary(true);
  }
}

async function loadLibrary(reset = true) {
  await ensureFields();
  if (!reset && (libLoading || (libTotal !== null && lastWorks.length >= libTotal))) return;
  const mySeq = reset ? ++libSeq : libSeq;
  if (reset) { libOffset = 0; lastWorks = []; libTotal = null; $("lib-list").className = "lib-grid " + libMode; $("lib-list").innerHTML = ""; }
  libLoading = true;
  const p = new URLSearchParams({ limit: LIB_PAGE, offset: libOffset });
  const q = $("search").value.trim(); if (q) p.set("q", q);
  if ($("search-field").value) p.set("search_field", $("search-field").value);
  if ($("sort-field").value) p.set("sort", $("sort-field").value);
  p.set("dir", $("sort-dir").value);
  if (reviewOnly) p.set("tag", "needs-review");
  const filters = currentFilters(); if (filters.length) p.set("filters", JSON.stringify(filters));
  const { data } = await api(`/api/works?${p.toString()}`);
  libLoading = false;
  if (!data || mySeq !== libSeq) return;          // superseded by a newer reset
  libTotal = data.total;
  const got = data.works || [];
  lastWorks = lastWorks.concat(got);
  libOffset = lastWorks.length;
  appendBooks(got);
  libDirty = false;   // cache is now fresh; tab returns will re-render from memory
  $("lib-count").textContent = `showing ${lastWorks.length} of ${libTotal}`;
}
const _coverBust = {};   // edition id -> timestamp, set after a cover is uploaded/replaced this session
function coverUrl(ed) {
  const cp = ed.cover_path || "";
  if (cp.startsWith("db:")) return `/api/cover/db/${ed.id}` + (_coverBust[ed.id] ? `?t=${_coverBust[ed.id]}` : "");
  const uuid = cp.replace("covers/", "").replace(".jpg", "");
  return uuid ? `/api/cover/${uuid}` : null;
}
const _MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
// Full publication date "as much as there is": real dates → "27 September 1960";
// year-only imports (stored as YYYY-01-01) and date-less records → just the year.
function fmtPubDate(ed) {
  const d = ed.published_date || "";
  const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    if (m[2] === "01" && m[3] === "01") return ed.year || m[1];   // year-only placeholder
    return `${+m[3]} ${_MONTHS[+m[2] - 1]} ${m[1]}`;
  }
  return ed.year ? String(ed.year) : "";
}
// Bibliographic facts for a work's primary edition, as [label, value] pairs — shared by
// the List view (no valuation) and the Detail view (with valuation).
function _idLabel(scheme) {
  return ({ goodreads: "Goodreads", asin: "ASIN (Amazon)", google: "Google Books",
    olid: "OpenLibrary", olid_work: "OpenLibrary (work)", isfdb: "ISFDB",
    google_work: "Google Books (work)" })[scheme] || scheme;
}
function bookFacts(w, { valuation = false } = {}) {
  const ed = w.editions[0] || {};
  const f = [];
  const add = (l, v) => { if (v !== null && v !== undefined && String(v).trim() !== "") f.push([l, String(v)]); };
  if (w.series) add("Series", w.series + (w.series_position ? ` #${w.series_position}` : ""));
  add("Published", fmtPubDate(ed));
  add("Publisher", ed.publisher);
  add("Format", ed.format);
  add("Language", ed.language);
  add("Original language", w.original_language);
  add("Pages", ed.pages);
  const byRole = {};
  (ed.contributors || []).forEach((c) => { if (c.name) (byRole[c.role || "contributor"] = byRole[c.role || "contributor"] || []).push(c.name); });
  Object.entries(byRole).forEach(([role, names]) => add(role.charAt(0).toUpperCase() + role.slice(1) + (names.length > 1 ? "s" : ""), names.join(", ")));
  add("ISBN-13", ed.isbn13);
  add("ISBN-10", ed.isbn10);
  // Goodreads and ISBN identifiers are intentionally not shown in views (ISBNs have their
  // own rows; Goodreads is internal — both are visible in the Stats data dictionary).
  (ed.identifiers || []).filter((i) => !/^isbn/i.test(i.scheme) && !/goodreads/i.test(i.scheme)).forEach((i) => add(_idLabel(i.scheme), i.value));
  if (ed.list_price != null) add("Cover price", ed.list_price + (ed.list_price_currency ? " " + ed.list_price_currency : ""));
  if ((w.tags || []).length) add("Genres / tags", w.tags.join(", "));
  const ncopies = w.editions.reduce((n, e) => n + e.copies.length, 0);
  add("Holdings", `${ncopies} ${ncopies === 1 ? "copy" : "copies"} · ${w.editions.length} edition${w.editions.length === 1 ? "" : "s"}`);
  if (valuation) {
    const cv = w.editions.flatMap((e) => e.copies).find((c) => c.current_value != null);
    add("Valuation", cv ? `${cv.current_value} ${cv.current_value_currency || ""}` : "— (set per copy below)");
  }
  return f;
}
function factsDl(facts) {
  const dl = document.createElement("dl"); dl.className = "facts";
  facts.forEach(([l, v]) => {
    const dt = document.createElement("dt"); dt.textContent = l;
    const dd = document.createElement("dd"); dd.textContent = v;
    dl.append(dt, dd);
  });
  return dl;
}
function bookEl(w, opts = {}) {
  const canWrite = currentUser && currentUser.role === "admin";
  const ed = w.editions[0] || {};
  const cu = coverUrl(ed);
  const ncopies = w.editions.reduce((n, e) => n + e.copies.length, 0);
  const ebook = w.editions.flatMap((e) => e.copies).find((c) => c.kind === "ebook" && c.file_ref);
  // With a cover: the image. Without: a same-size placeholder that shows the title.
  const img = cu ? `<img loading="lazy" src="${cu}" onerror="this.style.display='none'">` : `<div class="cover-ph"></div>`;
  const div = document.createElement("div");
  div.className = "book " + libMode;
  if (selectMode && selectedIds.has(w.id)) div.classList.add("selected");
  const open = () => (selectMode ? toggleSelect(w, div) : openDetail(w));
  div.innerHTML = img +
    `<div class="meta"><div class="t"></div><div class="a"></div><div class="body"></div><div class="acts"></div></div>`;
  div.querySelector(".t").textContent = w.title;
  div.querySelector(".a").textContent = (w.authors || []).join(", ");
  const body = div.querySelector(".body");
  if (libMode === "list") {
    // EXPANDED: every bibliographic detail the Detail tab shows, except valuation.
    body.appendChild(factsDl(bookFacts(w, { valuation: false })));
    const desc = (ed.description || "").trim();
    if (desc) { const p = document.createElement("div"); p.className = "bdesc"; p.textContent = desc; body.appendChild(p); }
  } else {
    // COMPACT grid: cover + title + author + a short sub-line (no ISBN).
    const sub = document.createElement("div"); sub.className = "sub";
    sub.textContent = [ed.year || "", ed.format || "", `${ncopies} ${ncopies === 1 ? "copy" : "copies"}`].filter(Boolean).join(" · ");
    body.appendChild(sub);
  }
  const titleEl = div.querySelector(".t"); titleEl.style.cursor = "pointer"; titleEl.addEventListener("click", open);
  const imgEl = div.querySelector("img"); if (imgEl) { imgEl.style.cursor = "pointer"; imgEl.addEventListener("click", open); }
  const ph = div.querySelector(".cover-ph");
  if (ph) { ph.textContent = w.title; ph.style.cursor = "pointer"; ph.addEventListener("click", open); }
  const acts = div.querySelector(".acts");
  const mk = (label, title, fn) => { const b = document.createElement("button"); b.className = "btn"; b.textContent = label; b.title = title; b.addEventListener("click", fn); acts.appendChild(b); };
  if (ebook) mk("⬇", "Open file", () => openEbook(ebook));
  if (canWrite) { mk("✦", "Enrich", () => enrichWork(w)); mk("✎", "Edit", () => editBook(w)); mk("🗑", "Delete", () => deleteBook(w)); }
  if (opts.onRemove) mk("−", "Remove from collection", opts.onRemove);
  return div;
}
function appendBooks(works) { const list = $("lib-list"); works.forEach((w) => list.appendChild(bookEl(w))); }
function renderLibrary(works) { const list = $("lib-list"); list.className = "lib-grid " + libMode; list.innerHTML = ""; appendBooks(works); }

// ---------- bulk select ----------
function toggleSelect(w, div) {
  if (selectedIds.has(w.id)) { selectedIds.delete(w.id); div.classList.remove("selected"); }
  else { selectedIds.add(w.id); div.classList.add("selected"); }
  $("bulk-count").textContent = `${selectedIds.size} selected`;
}
$("select-toggle").addEventListener("click", async () => {
  selectMode = !selectMode;
  $("select-toggle").classList.toggle("primary", selectMode);
  $("bulk-bar").classList.toggle("hidden", !selectMode);
  selectedIds.clear(); $("bulk-count").textContent = "0 selected";
  if (selectMode) fillCollSelect($("bulk-collection"), await fetchCollections("library"), "(choose collection)");
  renderLibrary(lastWorks);
});
$("bulk-clear").addEventListener("click", () => { selectedIds.clear(); $("bulk-count").textContent = "0 selected"; renderLibrary(lastWorks); });
$("bulk-add-coll").addEventListener("click", async () => {
  const cid = $("bulk-collection").value;
  if (!cid || !selectedIds.size) { return; }
  for (const id of [...selectedIds]) await api(`/api/collections/${cid}/works`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ work_id: id }) });
  alert(`Added ${selectedIds.size} book(s) to the collection.`);
});
$("bulk-delete").addEventListener("click", async () => {
  if (!selectedIds.size) return;
  if (!confirm(`Delete ${selectedIds.size} book(s) and all their copies?\n\nThis cannot be undone.`)) return;
  for (const id of [...selectedIds]) await api(`/api/works/${id}`, { method: "DELETE" });
  selectedIds.clear(); libDirty = true; loadLibrary(true);
});

// infinite scroll: load the next page as you near the bottom of the Library tab
window.addEventListener("scroll", () => {
  if ($("view-library").classList.contains("hidden")) return;
  if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 800) loadLibrary(false);
});

// ---------- book detail (Netflix-style) + 3D library map ----------
let currentDetailWork = null;
let _detailOpening = false;   // true only while freshly opening a book (one-shot, see renderDetail)
function openDetail(w) {
  currentDetailWork = w;
  _detailOpening = true;
  document.querySelector('.tab[data-view="detail"]').click();   // instant render from cache
  refreshDetail();   // then pull the complete data-model record and re-render in place
}
$("detail-back").addEventListener("click", () => document.querySelector('.tab[data-view="library"]').click());

function _setLines(el, lines) {
  el.innerHTML = "";
  lines.forEach((t) => { const d = document.createElement("div"); d.textContent = t; el.appendChild(d); });
}
function renderDetail() {
  const w = currentDetailWork;
  // Consume the one-shot flag: scroll to top only when freshly opening a book,
  // NOT on refreshDetail() re-renders (e.g. after marking a copy read).
  const opening = _detailOpening; _detailOpening = false;
  if (!w) { $("detail-empty").classList.remove("hidden"); $("detail-body").classList.add("hidden"); return; }
  $("detail-empty").classList.add("hidden"); $("detail-body").classList.remove("hidden");
  const ed = w.editions[0] || {};
  const cu = coverUrl(ed), cover = $("detail-cover");
  if (cu) { cover.src = cu; cover.style.display = ""; } else { cover.removeAttribute("src"); cover.style.display = "none"; }
  $("detail-title").textContent = w.title;
  // Authors with life dates when known (full record).
  const ad = w.authors_detail || [];
  $("detail-authors").textContent = ad.length
    ? ad.map((a) => a.name + ([a.birth_year, a.death_year].some((x) => x != null) ? ` (${a.birth_year || ""}–${a.death_year || ""})` : "")).join(", ")
    : (w.authors || []).join(", ");

  // The complete bibliographic record (with valuation) + author name-variants + dates.
  const metaEl = $("detail-meta"); metaEl.innerHTML = "";
  const facts = bookFacts(w, { valuation: true });
  if (!ed.isbn13 && !ed.isbn10) facts.push(["ISBN", "— none recorded (use Enrich or Find a Match)"]);
  ad.forEach((a) => { const alts = (a.name_forms || []).filter((nf) => nf !== a.name); if (alts.length) facts.push([`Other forms of ${a.name}`, alts.join("; ")]); });
  // Per-edition breakdown when a work has more than one edition.
  if (w.editions.length > 1) {
    w.editions.forEach((e, i) => {
      const bits = [e.isbn13 || e.isbn10, e.publisher, e.format, e.year, e.pages ? e.pages + "pp" : null].filter(Boolean).join(" · ");
      if (bits) facts.push([`Edition ${i + 1}`, bits]);
    });
  }
  if (w.created_at) facts.push(["Catalogued", w.created_at.slice(0, 10)]);
  if (w.updated_at) facts.push(["Last updated", w.updated_at.slice(0, 10)]);
  metaEl.appendChild(factsDl(facts));

  $("detail-tags").innerHTML = "";
  (w.tags || []).forEach((t) => { const s = document.createElement("span"); s.className = "badge"; s.textContent = t; $("detail-tags").appendChild(s); });
  $("detail-desc").textContent = ed.description || "";

  const acts = $("detail-actions"); acts.innerHTML = "";
  const mk = (label, fn, cls) => { const b = document.createElement("button"); b.className = "btn " + (cls || ""); b.textContent = label; b.addEventListener("click", fn); acts.appendChild(b); };
  if (currentUser && currentUser.role === "admin") {
    mk("✦ Enrich", () => enrichWork(w));
    mk("🔎 Find a Match", () => openMatchModal(w));
    mk("✎ Edit", () => editBook(w));
    mk("Delete", () => deleteBook(w));
  }

  // E-book versions: title + a button per format (EPUB / PDF / AZW3 …) opening the file.
  const ebx = $("detail-ebooks"); ebx.innerHTML = "";
  const ebooks = w.editions.flatMap((e) => e.copies).filter((c) => c.kind === "ebook" && c.file_ref);
  if (ebooks.length) {
    const row = document.createElement("div"); row.className = "ebook-row";
    const lbl = document.createElement("span"); lbl.className = "ebook-title"; lbl.textContent = "📚 E-book — " + w.title;
    row.appendChild(lbl);
    ebooks.forEach((c) => {
      const b = document.createElement("button"); b.className = "btn"; b.textContent = fileFmt(c.file_ref);
      b.title = "Open " + c.file_ref; b.addEventListener("click", () => openEbook(c)); row.appendChild(b);
    });
    ebx.appendChild(row);
  }

  const cl = $("detail-copies"); cl.innerHTML = "";
  w.editions.forEach((e) => e.copies.forEach((c) => {
    const d = document.createElement("div"); d.className = "item";
    d.innerHTML = `<div class="meta"><div class="t"></div><div class="sub"></div><div class="a"></div></div>`;
    d.querySelector(".t").textContent = [c.kind, c.copy_type, c.condition, c.condition_grade].filter(Boolean).join(" · ");
    const rs = (c.reading || [])[0];
    let readBit = "unread";
    if (rs) {
      if (rs.status === "read") readBit = "read" + ([rs.started, rs.finished].filter(Boolean).length ? " " + [rs.started, rs.finished].filter(Boolean).join("–") : "");
      else if (rs.status === "reading") readBit = "reading" + (rs.progress_pct ? ` ${rs.progress_pct}%` : "");
      else readBit = rs.status;
    }
    const openLoan = (c.loans || []).find((l) => !l.returned_date);
    const subBits = [
      c.location ? "📍 " + c.location : "no location",
      c.signed ? "signed" : null,
      readBit,
      c.acquired_date ? "acquired " + c.acquired_date : null,
      c.acquisition_price != null ? "paid " + c.acquisition_price + (c.acquisition_currency ? " " + c.acquisition_currency : "") : null,
      c.current_value != null ? "value " + c.current_value + (c.current_value_currency ? " " + c.current_value_currency : "") : null,
      openLoan ? "on loan to " + (openLoan.borrower || "?") + (openLoan.due_date ? " (due " + openLoan.due_date + ")" : "")
        : ((c.loans || []).length ? (c.loans.length + " past loan" + (c.loans.length > 1 ? "s" : "")) : null),
      c.created_at ? "added " + c.created_at.slice(0, 10) : null,
    ].filter(Boolean);
    d.querySelector(".sub").textContent = subBits.join(" · ");
    const noteLine = [c.notes, c.file_ref ? "📄 " + c.file_ref : null].filter(Boolean).join("  ·  ");
    d.querySelector(".a").textContent = noteLine;
    if (c.kind === "ebook" && c.file_ref) {
      const dl = document.createElement("div"); dl.className = "btn-row";
      const b = document.createElement("button"); b.className = "btn"; b.textContent = "⬇ Open file";
      b.addEventListener("click", () => openEbook(c)); dl.appendChild(b);
      d.querySelector(".meta").appendChild(dl);
    }
    if (currentUser && currentUser.role === "admin") {
      const ctl = document.createElement("div"); ctl.className = "btn-row";
      [["📖 Reading", "reading"], ["✓ Read", "read"], ["○ Unread", "unread"]].forEach(([label, st]) => {
        const b = document.createElement("button"); b.className = "btn"; b.textContent = label;
        b.addEventListener("click", () => setCopyReading(c.id, st)); ctl.appendChild(b);
      });
      const vb = document.createElement("button"); vb.className = "btn"; vb.textContent = "💷 Value";
      vb.addEventListener("click", () => valueCopy(c)); ctl.appendChild(vb);
      d.querySelector(".meta").appendChild(ctl);
    }
    cl.appendChild(d);
  }));

  renderDetailCollections(w);
  renderMap(w, opening);
  if (opening) window.scrollTo(0, 0);   // always land at the top of the page
}

async function refreshDetail() {
  if (!currentDetailWork) return;
  const { data } = await api(`/api/works/${currentDetailWork.id}`);
  if (data && data.id) { currentDetailWork = data; renderDetail(); }
}
async function setCopyReading(copyId, st) {
  await api(`/api/copies/${copyId}/reading`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: st }) });
  libDirty = true; refreshDetail();
}
async function valueCopy(c) {
  const mp = prompt("Current market price for a copy like this (what it sells for now)?");
  if (!mp) return;
  const cond = c.condition === "new" ? 1.4 : (c.condition === "used" ? 0.9 : 1.0);
  const r = await api(`/api/copies/${c.id}/value`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ market_price: mp, condition: cond }) });
  if (r.ok) { libDirty = true; refreshDetail(); } else alert(r.data?.error || "Failed");
}
function buyWishlist(item) {
  const parts = (item.title || "").split(" — ");
  document.querySelector('.tab[data-view="add"]').click();
  setDest("library"); resetForm();
  $("title").value = parts[0] || item.title || "";
  if (parts[1]) $("authors").value = parts[1].split(",").map((x) => x.trim()).filter(Boolean).join("\n");
  const mm = (item.notes || "").match(/ISBN\s*([0-9Xx]+)/i); if (mm) $("isbn").value = mm[1];
  buyingWishlistId = item.id;
  status($("save-status"), `From wishlist: “${parts[0] || item.title}”. Add copy details and Save to move it into your library.`, "info");
  window.scrollTo(0, 0);
}

async function renderDetailCollections(w) {
  const box = $("detail-collection"); box.innerHTML = "";
  if (!(currentUser && currentUser.role === "admin")) return;
  const cols = await fetchCollections("library");
  const sel = document.createElement("select");
  sel.add(new Option(cols.length ? "Add to collection…" : "(create a collection first)", ""));
  cols.forEach((c) => sel.add(new Option(c.name, c.id)));
  const btn = document.createElement("button"); btn.className = "btn"; btn.textContent = "+ Add to collection";
  btn.addEventListener("click", async () => {
    if (!sel.value) return;
    const r = await api(`/api/collections/${sel.value}/works`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ work_id: w.id }) });
    if (r.ok) { btn.textContent = "✓ Added"; setTimeout(() => { btn.textContent = "+ Add to collection"; }, 1500); }
  });
  box.append(sel, btn);
}

// location "UK 33" -> {area:"UK", shelf:"33"}; "Greece" -> {area:"Greece", shelf:null}
function parseLoc(loc) {
  const s = String(loc).replace(/[,\s]+$/, "");
  const mm = s.match(/^(.*?)\s*(\d+)$/);
  return mm ? { area: mm[1].trim(), shelf: mm[2] } : { area: s.trim(), shelf: null };
}
let MAPS = null;
async function getMaps() {
  if (MAPS) return MAPS;
  const { data } = await api("/api/maps");
  MAPS = {};
  (data?.maps || []).forEach((x) => { MAPS[x.area.toLowerCase()] = x; });
  return MAPS;
}
async function renderMap(w, opening) {
  const note = $("detail-shelf-note"), frame = $("libmap"), bar = $("detail-map-targets");
  bar.innerHTML = "";
  const copies = w.editions.flatMap((e) => e.copies);
  const locs = copies.map((c) => c.location).filter(Boolean);
  if (!locs.length) { note.textContent = "No location recorded for this book."; frame.style.display = "none"; frame.removeAttribute("src"); return; }
  const maps = await getMaps();
  const seen = new Set(), targets = [], unmatchedAreas = new Set();
  copies.forEach((c) => {
    if (!c.location) return;
    const { area, shelf } = parseLoc(c.location);
    const cfg = area ? maps[area.toLowerCase()] : null;
    if (cfg && shelf) { const k = cfg.id + ":" + shelf; if (!seen.has(k)) { seen.add(k); targets.push({ ...cfg, shelf, loc: c.location }); } }
    else unmatchedAreas.add(area || c.location);
  });
  if (!targets.length) {
    frame.style.display = "none"; frame.removeAttribute("src");
    note.textContent = `Location(s): ${locs.join(", ")} — no 3D map yet for ${[...unmatchedAreas].join(", ")} (add one in Admin → Library maps).`;
    return;
  }
  frame.style.display = "";
  const show = (t) => {
    // On a fresh open, the 3D map can grab focus and scroll itself into view;
    // pin the page back to the top once it loads. (Not on later shelf-button clicks.)
    if (opening) {
      frame.onload = () => { window.scrollTo(0, 0); requestAnimationFrame(() => window.scrollTo(0, 0)); frame.onload = null; };
      opening = false;
    }
    frame.src = t.asset_path + "?shelf=" + t.shelf;
    note.textContent = `${t.loc} → ${t.name}, shelf ${t.shelf}` +
      (unmatchedAreas.size ? ` · no map yet for: ${[...unmatchedAreas].join(", ")}` : "");
    [...bar.children].forEach((b) => b.classList.toggle("primary", b._t === t));
  };
  if (targets.length > 1) targets.forEach((t) => { const b = document.createElement("button"); b.className = "btn"; b._t = t; b.textContent = `${t.name} · shelf ${t.shelf}`; b.addEventListener("click", () => show(t)); bar.appendChild(b); });
  show(targets[0]);
}

// ---------- enrichment ----------
async function enrichWork(w) {
  const ids = (w.editions || []).map((e) => e.id);
  const { ok, data } = await api("/api/enrichment/dry-run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edition_ids: ids, note: w.title }),
  });
  if (!ok) { alert(data?.error || "Enrichment failed"); return; }
  if (!data.proposals.length) {
    alert("There is no new metadata to add.");
    api(`/api/enrichment/runs/${data.run_id}/commit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "none" }) });
    return;
  }
  document.querySelector('.tab[data-view="enrich"]').click();
  renderEnrich(data, w.title);
}
function renderEnrich(diff, title) {
  currentRun = diff.run_id;
  const box = $("enrich-proposals"); box.innerHTML = "";
  status($("enrich-status"), `${diff.proposals.length} proposed change(s) for “${title || ""}”. Review, then apply.`, "info");
  diff.proposals.forEach((p) => {
    const row = document.createElement("div"); row.className = "item"; row.dataset.pid = p.id;
    row.innerHTML =
      `<label class="chk"><input type="checkbox" class="p-sel" ${p.change_type === "add" ? "checked" : ""}></label>
       <div class="meta"><div class="t">${p.field} <span class="badge">${p.change_type}</span></div>
       <div class="sub">current:</div><div class="a cur"></div>
       <div class="sub">proposed (${p.source}):</div><div class="a prop"></div></div>`;
    row.querySelector(".cur").textContent = p.current ?? "—";
    row.querySelector(".prop").textContent = p.proposed ?? "—";
    box.appendChild(row);
  });
  $("enrich-actions").classList.remove("hidden");
}
$("enrich-all-sel").addEventListener("change", (e) => {
  document.querySelectorAll("#enrich-proposals .p-sel").forEach((c) => { c.checked = e.target.checked; });
});
async function commitEnrich(mode, picked) {
  if (!currentRun) return;
  const ss = $("enrich-status");
  if (mode === "selected") await api(`/api/enrichment/runs/${currentRun}/select`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proposal_ids: picked }) });
  const { ok, data } = await api(`/api/enrichment/runs/${currentRun}/commit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
  if (ok) { status(ss, mode === "none" ? "Discarded — nothing changed." : `Applied ${data.applied} change(s).`, "ok"); $("enrich-proposals").innerHTML = ""; $("enrich-actions").classList.add("hidden"); currentRun = null; }
  else status(ss, data?.error || "Failed", "error");
}
$("enrich-apply-selected").addEventListener("click", () => {
  const picked = [...document.querySelectorAll("#enrich-proposals .item")].filter((r) => r.querySelector(".p-sel").checked).map((r) => r.dataset.pid);
  commitEnrich("selected", picked);
});
$("enrich-apply-all").addEventListener("click", () => commitEnrich("all"));
$("enrich-discard").addEventListener("click", () => commitEnrich("none"));

// ---------- wishlist (with collections) ----------
async function loadWishlist() {
  fillCollSelect($("wish-coll-select"), await fetchCollections("wishlist"), "All wishlist items");
  const cid = $("wish-coll-select").value;
  const { data } = await api("/api/wishlist" + (cid ? "?collection_id=" + cid : ""));
  const list = $("wish-list"); list.innerHTML = "";
  if (!data.items?.length) { list.innerHTML = `<div class="hint-row">No wishlist items here yet.</div>`; return; }
  data.items.forEach((w) => {
    const div = document.createElement("div"); div.className = "item";
    div.innerHTML = `<div class="meta"><div class="t"></div>
      <div class="sub">${w.target_price ? "target " + w.target_price + " " + (w.currency || "") : ""} ${w.priority ? "· P" + w.priority : ""}</div>
      <div class="a"></div></div><button class="del" title="remove">✕</button>`;
    div.querySelector(".t").textContent = w.title || "(untitled)";
    div.querySelector(".a").textContent = w.notes || "";
    div.querySelector(".del").addEventListener("click", async () => { await api(`/api/wishlist/${w.id}`, { method: "DELETE" }); loadWishlist(); });
    if (currentUser && currentUser.role === "admin") {
      const buy = document.createElement("button"); buy.className = "btn"; buy.textContent = "🛒→Library"; buy.title = "I bought it — add to library";
      buy.addEventListener("click", () => buyWishlist(w));
      div.insertBefore(buy, div.querySelector(".del"));
    }
    list.appendChild(div);
  });
}
$("wish-coll-select").addEventListener("change", loadWishlist);
$("wish-coll-new").addEventListener("click", async () => { const c = await createCollection("wishlist"); if (c) { await loadWishlist(); $("wish-coll-select").value = c.id; loadWishlist(); } });

// ---------- Library Collections tab ----------
async function loadCollectionsTab() {
  fillCollSelect($("coll-select"), await fetchCollections("library"), "— choose a collection —");
  renderCollectionWorks();
}
$("coll-select").addEventListener("change", renderCollectionWorks);
$("coll-new").addEventListener("click", async () => { const c = await createCollection("library"); if (c) { await loadCollectionsTab(); $("coll-select").value = c.id; renderCollectionWorks(); } });
async function renderCollectionWorks() {
  const cid = $("coll-select").value, list = $("coll-list"), info = $("coll-info");
  list.className = "lib-grid " + libMode; list.innerHTML = "";
  if (!cid) { info.textContent = "Pick or create a collection. Add books to it from a book's Detail page (Add to collection)."; return; }
  const { data } = await api(`/api/works?collection_id=${cid}&limit=300`);
  info.textContent = `${data.total} book(s) in this collection`;
  (data.works || []).forEach((w) => list.appendChild(bookEl(w, {
    onRemove: async () => { await api(`/api/collections/${cid}/works/${w.id}`, { method: "DELETE" }); renderCollectionWorks(); },
  })));
}

// ---------- admin ----------
function loadAdmin() {
  const admin = currentUser && currentUser.role === "admin";
  $("appearance-card").classList.toggle("hidden", !admin);
  if (admin) loadSkinPicker();
  $("ebook-card").classList.toggle("hidden", !admin);
  $("import-card").classList.toggle("hidden", !admin);
  $("backup-card").classList.toggle("hidden", !admin);
  $("maps-card").classList.toggle("hidden", !admin);
  $("sources-card").classList.toggle("hidden", !admin);
  $("custom-sources-card").classList.toggle("hidden", !admin);
  $("admin-card").classList.toggle("hidden", !admin);
  if (admin) { loadUsers(); loadSources(); loadCustomSources(); loadMaps(); populateImpCollections(); loadEbookFolder(); }
}

// ---- E-book folder scan ----
async function loadEbookFolder() {
  const { ok, data } = await api("/api/settings");
  if (!ok) return;
  $("eb-dir").value = data.ebooks_dir || "";
  $("eb-dir-note").textContent = data.ebooks_dir
    ? (data.ebooks_dir_exists ? "" : "⚠ this folder isn't reachable from the server right now")
    : "No folder chosen yet — pick one to enable scanning.";
}
$("eb-browse").addEventListener("click", () => {
  openFolderPicker(async (path) => {
    const { ok, data } = await api("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ebooks_dir: path }),
    });
    if (ok) { $("eb-dir").value = data.ebooks_dir || ""; loadEbookFolder(); }
    else { status($("eb-status"), data?.error || "Could not set folder", "error"); }
  }, $("eb-dir").value || null);
});
$("eb-scan").addEventListener("click", async () => {
  const ss = $("eb-status");
  status(ss, "Scanning e-book folder…", "info");
  const body = JSON.stringify({ lookup: $("eb-lookup").checked });
  const { ok, data } = await api("/api/ebooks/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  if (ok) {
    status(ss, `✓ Scanned ${data.scanned} file(s): +${data.added} new, ${data.skipped} already in catalog.`, "ok");
    if (data.added) libDirty = true;
  } else status(ss, data?.error || "Failed", "error");
});

// ---- CSV import ----
let impRows = [];
async function populateImpCollections() {
  const cols = await fetchCollections($("imp-dest").value);
  const sel = $("imp-collection"); sel.innerHTML = "";
  sel.add(new Option("(no collection)", ""));
  sel.add(new Option("+ New collection…", "__new__"));
  cols.forEach((c) => sel.add(new Option(c.name, c.id)));
}
$("imp-dest").addEventListener("change", populateImpCollections);
$("imp-collection").addEventListener("change", async (e) => {
  if (e.target.value === "__new__") {
    const c = await createCollection($("imp-dest").value);
    await populateImpCollections();
    $("imp-collection").value = c ? c.id : "";
  }
});
$("imp-preview").addEventListener("click", async () => {
  const ss = $("imp-status"), f = $("imp-file").files[0];
  if (!f) { status(ss, "Choose a CSV file.", "error"); return; }
  status(ss, "Parsing…", "info");
  const fd = new FormData(); fd.append("file", f);
  const { ok, data } = await api("/api/import/preview", { method: "POST", body: fd });
  if (!ok) { status(ss, data?.error || "Failed", "error"); return; }
  impRows = data.rows || [];
  $("imp-summary").textContent = `${data.total} rows in file, showing ${data.shown}. Detected columns: ${Object.keys(data.columns).join(", ") || "none"}.`;
  const box = $("imp-rows"); box.innerHTML = "";
  impRows.forEach((r, i) => {
    const row = document.createElement("div"); row.className = "item"; row.dataset.i = i;
    row.innerHTML = `<label class="chk"><input type="checkbox" class="imp-sel" ${r.eligible ? "checked" : "disabled"}></label>
      <div class="meta"><div class="t"></div><div class="sub"></div></div>`;
    row.querySelector(".t").textContent = r.title || "(no title)";
    row.querySelector(".sub").textContent = [(r.authors || []).join(", "), r.isbn ? "ISBN " + r.isbn : "", r.asin ? "ASIN " + r.asin : "", r.year].filter(Boolean).join(" · ") || "—";
    box.appendChild(row);
  });
  status(ss, "Review, then Import selected.", "ok");
});
$("imp-commit").addEventListener("click", async () => {
  const ss = $("imp-status");
  const chosen = [...document.querySelectorAll("#imp-rows .item")]
    .filter((r) => { const cb = r.querySelector(".imp-sel"); return cb && cb.checked; })
    .map((r) => impRows[+r.dataset.i]);
  if (!chosen.length) { status(ss, "No rows selected.", "error"); return; }
  const coll = $("imp-collection").value;
  status(ss, `Importing ${chosen.length}…`, "info");
  const { ok, data } = await api("/api/import/commit", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows: chosen, destination: $("imp-dest").value,
      collection_id: coll && coll !== "__new__" ? coll : null, do_lookup: $("imp-lookup").checked }),
  });
  if (ok) { status(ss, `✓ Added ${data.added}, skipped ${data.skipped}${data.enriched ? `, enriched ${data.enriched}` : ""}.`, "ok"); $("imp-rows").innerHTML = ""; impRows = []; libDirty = true; }
  else status(ss, data?.error || "Failed", "error");
});

async function loadMaps() {
  const { data } = await api("/api/maps");
  const list = $("maps-list"); list.innerHTML = "";
  (data?.maps || []).forEach((x) => {
    const row = document.createElement("div"); row.className = "item admin-row";
    row.innerHTML = `<div class="meta"><div class="t"></div><div class="sub"></div></div><button class="btn del"></button>`;
    row.querySelector(".t").textContent = `${x.name}  ·  area "${x.area}"`;
    row.querySelector(".sub").textContent = x.asset_path;
    row.querySelector(".del").textContent = `Delete "${x.name}"`;
    row.querySelector(".del").addEventListener("click", async () => {
      if (!confirm(`Delete the 3D map "${x.name}" (area "${x.area}")?`)) return;
      await api(`/api/maps/${x.id}`, { method: "DELETE" }); MAPS = null; loadMaps();
    });
    list.appendChild(row);
  });
}
$("map-add").addEventListener("click", async () => {
  const ss = $("map-status");
  const area = $("map-area").value.trim(), f = $("map-file").files[0];
  if (!area) { status(ss, "Area prefix required.", "error"); return; }
  if (!f) { status(ss, "Choose the map's HTML file.", "error"); return; }
  const fd = new FormData(); fd.append("area", area); fd.append("name", $("map-name").value.trim() || area); fd.append("file", f);
  const { ok, data } = await api("/api/maps", { method: "POST", body: fd });
  if (ok) { status(ss, "✓ Map saved.", "ok"); $("map-area").value = ""; $("map-name").value = ""; $("map-file").value = ""; MAPS = null; loadMaps(); }
  else status(ss, data?.error || "Failed", "error");
});
$("cp-btn").addEventListener("click", async () => {
  const ss = $("cp-status");
  const { ok, data } = await api("/api/auth/change-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current: $("cp-current").value, new: $("cp-new").value }) });
  if (ok) { status(ss, "✓ Password updated.", "ok"); $("cp-current").value = ""; $("cp-new").value = ""; }
  else status(ss, data?.error || "Failed", "error");
});

// backups (with optional save-location picker)
async function downloadFile(url, baseName, ext) {
  const ss = $("backup-status"); status(ss, `Preparing ${baseName}…`, "info");
  const r = await fetch(url);
  if (!r.ok) { status(ss, `Failed (HTTP ${r.status})`, "error"); return; }
  const blob = await r.blob();
  const name = `${baseName}-${tsClient()}.${ext}`;
  if (window.showSaveFilePicker) {
    try {
      const h = await window.showSaveFilePicker({ suggestedName: name });
      const w = await h.createWritable(); await w.write(blob); await w.close();
      status(ss, `Saved ${name}`, "ok"); return;
    } catch (e) { if (e.name === "AbortError") { status(ss, "Cancelled", null); return; } }
  }
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; a.click();
  URL.revokeObjectURL(a.href); status(ss, `Downloaded ${name}`, "ok");
}
document.querySelectorAll("[data-bk]").forEach((b) =>
  b.addEventListener("click", () => downloadFile(b.dataset.bk, b.dataset.name, b.dataset.bk.split(".").pop())));

// enrichment sources
async function loadSources() {
  const { data } = await api("/api/enrichment/sources"); if (!data) return;
  const list = $("sources-list"); list.innerHTML = "";
  const present = new Set((data.sources || []).map((s) => s.key));
  const sel = $("ns-key"); sel.innerHTML = "";
  (data.available || []).filter((k) => !present.has(k)).forEach((k) => { const o = document.createElement("option"); o.value = k; o.textContent = k; sel.appendChild(o); });
  (data.sources || []).forEach((src) => {
    const row = document.createElement("div"); row.className = "item admin-row";
    row.innerHTML = `<label class="chk inline" title="Enable this source"><input type="checkbox" class="en" ${src.enabled ? "checked" : ""}></label>
      <div class="meta"><div class="t"></div></div>
      <label class="prio-lbl">priority <input type="number" class="prio" value="${src.priority}"></label>
      <button class="btn del"></button>`;
    const t = row.querySelector(".t");
    t.textContent = src.name + " ";
    const kb = document.createElement("span"); kb.className = "badge"; kb.textContent = src.key; t.appendChild(kb);
    if (!src.fetchable) { const ib = document.createElement("span"); ib.className = "badge"; ib.style.marginLeft = ".35rem"; ib.textContent = "inert"; t.appendChild(ib); }
    row.querySelector(".del").textContent = `Delete ${src.name}`;
    row.querySelector(".en").addEventListener("change", (e) => api(`/api/enrichment/sources/${src.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: e.target.checked }) }));
    row.querySelector(".prio").addEventListener("change", (e) => api(`/api/enrichment/sources/${src.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ priority: parseInt(e.target.value) || 100 }) }));
    row.querySelector(".del").addEventListener("click", async () => {
      if (!confirm(`Delete enrichment source "${src.name}"? Lookups will stop using it.`)) return;
      await api(`/api/enrichment/sources/${src.id}`, { method: "DELETE" }); loadSources();
    });
    list.appendChild(row);
  });
}
$("ns-btn").addEventListener("click", async () => {
  const key = $("ns-key").value;
  if (!key) { status($("ns-status"), "No source types left to add.", "error"); return; }
  const { ok, data } = await api("/api/enrichment/sources", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key, name: key }) });
  if (ok) loadSources(); else status($("ns-status"), data?.error || "Failed", "error");
});

// custom SRU catalogue sources
async function loadCustomSources() {
  const { data } = await api("/api/sources/custom"); if (!data) return;
  const list = $("custom-sources-list"); list.innerHTML = "";
  (data.sources || []).forEach((s) => {
    const row = document.createElement("div"); row.className = "item admin-row";
    row.innerHTML = `<div class="meta"><div class="t"></div><div class="sub"></div></div><button class="btn del"></button>`;
    row.querySelector(".t").textContent = s.name;
    row.querySelector(".sub").textContent = s.url;
    const del = row.querySelector(".del"); del.textContent = `Delete "${s.name}"`;
    del.addEventListener("click", async () => {
      if (!confirm(`Delete catalogue source "${s.name}"?`)) return;
      await api(`/api/sources/custom/${s.key}`, { method: "DELETE" }); loadCustomSources();
    });
    list.appendChild(row);
  });
}
$("cs-add").addEventListener("click", async () => {
  const name = $("cs-name").value.trim(), url = $("cs-url").value.trim();
  if (!name || !url) { status($("cs-status"), "Name and SRU URL are required.", "error"); return; }
  const { ok, data } = await api("/api/sources/custom", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, url }) });
  if (ok) { status($("cs-status"), `✓ Added “${name}”. It now appears in Find a Match.`, "ok"); $("cs-name").value = ""; $("cs-url").value = ""; _matchSourcesLoaded = false; loadCustomSources(); }
  else status($("cs-status"), data?.error || "Failed", "error");
});

// users
async function loadUsers() {
  const { data } = await api("/api/users"); if (!data?.users) return;
  const list = $("users-list"); list.innerHTML = "";
  data.users.forEach((u) => {
    const self = currentUser && u.username === currentUser.username;
    const row = document.createElement("div"); row.className = "item";
    row.innerHTML = `<div class="meta"><div class="t"></div>
      <div class="sub">role: <select class="role-sel" ${self ? "disabled" : ""}>
        <option value="consumer">consumer</option><option value="admin">admin</option></select></div></div>
      <button class="btn rstpw" title="reset password">🔑</button>
      <button class="del" ${self ? "disabled" : ""}>✕</button>`;
    row.querySelector(".t").textContent = u.username + (self ? " (you)" : "");
    row.querySelector(".role-sel").value = u.role;
    row.querySelector(".role-sel").addEventListener("change", async (e) => { const r = await api(`/api/users/${u.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: e.target.value }) }); if (!r.ok) { alert(r.data?.error || "Failed"); loadUsers(); } });
    row.querySelector(".rstpw").addEventListener("click", async () => { const np = prompt(`New password for ${u.username} (min 6):`); if (!np) return; const r = await api(`/api/users/${u.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: np }) }); alert(r.ok ? "Password reset." : (r.data?.error || "Failed")); });
    row.querySelector(".del").addEventListener("click", async () => { if (!confirm(`Delete ${u.username}?`)) return; const r = await api(`/api/users/${u.id}`, { method: "DELETE" }); if (r.ok) loadUsers(); else alert(r.data?.error || "Failed"); });
    list.appendChild(row);
  });
}
$("nu-btn").addEventListener("click", async () => {
  const ss = $("nu-status");
  const { ok, data } = await api("/api/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("nu-name").value.trim(), role: $("nu-role").value, password: $("nu-pass").value }) });
  if (ok) { status(ss, "✓ User created.", "ok"); $("nu-name").value = ""; $("nu-pass").value = ""; loadUsers(); }
  else status(ss, data?.error || "Failed", "error");
});

// ---------- e-book file open/download ----------
function openEbook(copy) {
  if (!copy || !copy.file_ref) { alert("No e-book file for this copy."); return; }
  // Streams the file from the e-book folder; the browser opens or downloads it.
  window.open(`/api/ebooks/file/${copy.id}`, "_blank");
}

// ---------- auth ----------
function showLogin() { $("login-overlay").classList.remove("hidden"); $("logout-btn").classList.add("hidden"); }
function showApp(user) {
  currentUser = user;
  $("login-overlay").classList.add("hidden"); $("logout-btn").classList.remove("hidden");
  const admin = user.role === "admin";
  $("who").textContent = user.username + (admin ? "" : " (consumer)");
  // consumers: hide library-write tabs (Enrich/Admin). They keep Add but it's wishlist-only.
  ["enrich", "stats", "metadata", "admin"].forEach((v) => {
    const t = document.querySelector(`.tab[data-view="${v}"]`); if (t) t.style.display = admin ? "" : "none";
  });
  $("dest-card").style.display = admin ? "" : "none";   // consumers can't choose Library
  $("select-toggle").style.display = admin ? "" : "none";   // bulk actions are admin-only
  $("discover-btn").style.display = admin ? "" : "none";    // TALPA discovery is admin-only
  if (admin) api("/api/discover/status").then(({ data }) => { if (data && !data.configured) $("discover-btn").style.display = "none"; });
  if (!admin) setDest("wishlist");
  applyServerSkin();
  // Always open on the Library view (not the Add form).
  document.querySelector('.tab[data-view="library"]').click();
}
async function checkAuth() { const r = await fetch("/api/auth/me"); if (r.ok) showApp(await r.json()); else showLogin(); }
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ss = $("login-status");
  const r = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: $("login-user").value.trim(), password: $("login-pass").value }) });
  const data = await r.json().catch(() => ({}));
  if (r.ok) { $("login-pass").value = ""; ss.classList.add("hidden"); showApp(data); }
  else status(ss, data.error || "Login failed", "error");
});
$("logout-btn").addEventListener("click", async () => { await fetch("/api/auth/logout", { method: "POST" }); showLogin(); });
checkAuth();

// ---------- service worker ----------
if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
