"use strict";

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const api = (p, opts) => fetch(p, opts).then(r => r.json());

const state = {
  targets: [],          // matrix rows
  selected: new Set(),
  config: {},
  running: false,
};

/* ── tabs ─────────────────────────────────────────────── */
$$(".tab").forEach(t => t.addEventListener("click", () => {
  $$(".tab").forEach(x => x.classList.remove("is-active"));
  $$(".panel").forEach(x => x.classList.remove("is-active"));
  t.classList.add("is-active");
  $("#tab-" + t.dataset.tab).classList.add("is-active");
}));

/* ── machine spec ─────────────────────────────────────── */
function renderSpec(h) {
  state.host = h;
  const ram  = h.ram_gb != null ? `${h.ram_gb}<span class="u"> GB</span>` : "—";
  const disk = h.free_disk_gb != null ? `${h.free_disk_gb}<span class="u">${t("spec.gbFree")}</span>` : "—";
  const rows = [
    ["host",  h.hostname || "—"],
    ["os",    `<span class="spec-os">${h.os} ${h.os_release || ""}</span>`],
    ["arch",  h.arch],
    ["cpu",   h.cpu],
    ["cores", `${h.cores_logical}`],
    ["ram",   ram],
    ["disk",  disk],
  ];
  if (h.distro) rows.splice(2, 0, ["distro", h.distro]);
  $("#spec").innerHTML = rows.map(([k, v]) =>
    `<div class="spec-row"><span class="spec-k">${t("spec." + k)}</span><span class="spec-v">${v}</span></div>`
  ).join("");
}

/* ── prereqs ──────────────────────────────────────────── */
// map of tool id -> full row from /api/toolchains
state.installable = {};
state.localTotal = "";

function renderPrereqs(list) {
  state.prereqs = list;
  $("#prereqs").innerHTML = list.map(p => {
    const ok = p.present;
    const inst = state.installable[p.id];
    const canInstall = !ok && inst && inst.installable;
    const cls = ok ? "ok" : "no";
    const hint = (!ok && p.hint && !canInstall) ? `<div class="pr-hint">${esc(p.hint)}</div>` : "";

    let right;
    if (canInstall) {
      const sz = inst.id === "vs_buildtools" ? inst.size_disk : inst.size_download;
      const dl = sz ? ` <span class="pr-size">${esc(sz)}</span>` : "";
      right = `<button class="pr-install" data-install="${inst.id}">${t("tool.install")}${dl}</button>`;
    } else if (ok) {
      const ver = esc(shortVer(p.version)) || t("tool.ok");
      // if it came from our local .toolchains folder, show its size + a remove ✕
      const rm = inst && inst.local
        ? ` <span class="pr-local" title="${t("tool.localTitle")}">${esc(inst.local_size)}<button class="pr-remove" data-remove="${p.id}" title="${t("tool.removeTitle")}">✕</button></span>`
        : "";
      right = `<span class="pr-ver" title="${esc(p.version || "")}">${ver}</span>${rm}`;
    } else {
      right = `<span class="pr-ver">${t("tool.notFound")}</span>`;
    }

    return `<li class="pr ${ok ? "" : "missing"}">
      <div class="pr-top">
        <span class="pr-dot ${cls}"></span>
        <span class="pr-name">${esc(p.label)}</span>
        ${right}
      </div>${hint}</li>`;
  }).join("");

  const anyInstallable = list.some(p => !p.present && state.installable[p.id]?.installable);
  $("#install-missing").hidden = !anyInstallable;
  // local footprint line
  const foot = $("#local-foot");
  if (state.localTotal && state.localTotal !== "0 B") {
    foot.hidden = false;
    foot.innerHTML = `${t("tool.localFoot")}<strong>${esc(state.localTotal)}</strong> <code>.toolchains/</code>`;
  } else {
    foot.hidden = true;
  }
}
const shortVer = v => (v || "").replace(/^[^\d]*/, "").split(" ")[0] || v || "";

async function loadToolchains() {
  try {
    const t = await api("/api/toolchains");
    state.installable = {};
    // key by the prereq id each tool satisfies (e.g. vs_buildtools -> "msbuild"),
    // so the sidebar rows can find their installer. Value keeps the real tool id.
    t.tools.forEach(x => state.installable[x.satisfies || x.id] = x);
    state.localTotal = t.local_total || "";
  } catch { state.installable = {}; }
}

/* ── toolchain install ────────────────────────────────── */
const icon = $("#install-console");
function installLine(text) {
  const span = document.createElement("span");
  if (/✓|installed|done\./.test(text)) span.className = "con-ok";
  else if (/✗|failed|error/i.test(text)) span.className = "con-err";
  else if (/^===|↓/.test(text.trim())) span.className = "con-head";
  span.textContent = text + "\n";
  icon.appendChild(span);
  icon.scrollTop = icon.scrollHeight;
}

async function installTools(ids) {
  if (!ids.length) return;
  if (ids.includes("vs_buildtools")) {
    if (!confirm(t("tool.vsConfirm"))) return;
  }
  $("#install-log").hidden = false;
  $("#install-log-title").textContent = t("tool.installingX", { ids: ids.join(", ") });
  icon.textContent = "";
  const r = await api("/api/toolchains/install", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!r.ok) { installLine("!! " + (r.message || r.error || t("build.couldNotStart"))); return; }
  $("#install-missing").disabled = true;
  const es = new EventSource("/api/toolchains/stream");
  es.onmessage = ev => { try { installLine(JSON.parse(ev.data).line); } catch {} };
  es.addEventListener("done", async () => {
    es.close();
    $("#install-log-title").textContent = t("tool.finished");
    $("#install-missing").disabled = false;
    await loadToolchains();
    await api("/api/prereqs").then(renderPrereqs);
    await loadMatrix();
    $("#install-log-title").textContent = t("tool.done");
  });
  es.onerror = () => {};
}

$("#install-missing").addEventListener("click", () => {
  const ids = Object.values(state.installable)
    .filter(x => x.installable && !x.present && x.id !== "vs_buildtools")
    .map(x => x.id);
  installTools(ids);
});
$("#install-cancel").addEventListener("click", () =>
  api("/api/toolchains/cancel", { method: "POST" }));
document.addEventListener("click", e => {
  const b = e.target.closest("[data-install]");
  if (b) { installTools([b.dataset.install]); return; }
  const rm = e.target.closest("[data-remove]");
  if (rm) removeTool(rm.dataset.remove);
});

async function removeTool(id) {
  const inst = state.installable[id];
  const size = inst?.local_size ? ` (${inst.local_size})` : "";
  if (!confirm(t("tool.removeConfirm", { id, size }))) return;
  await api("/api/toolchains/remove", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  await loadToolchains();
  await api("/api/prereqs").then(renderPrereqs);
  await loadMatrix();
}

/* ── capability board ─────────────────────────────────── */
function renderBoard() {
  const order = { android: 0, windows: 1, linux: 2, macos: 3 };
  const rows = [...state.targets].sort((a, b) =>
    (order[a.platform] - order[b.platform]) || a.label.localeCompare(b.label));

  $("#board").innerHTML = rows.map((tg, i) => {
    let kind = "blocked";
    if (tg.buildable && tg.ready) kind = "ready";
    else if (tg.buildable && !tg.ready) kind = "need";

    let reason = "";
    if (kind === "need") reason = t("targets.installFirst", { tools: tg.missing_tools.join(", ") });
    else if (kind === "blocked") reason = tg.blocked_reason;
    else if (tg.blocked_reason) reason = tg.blocked_reason;  // e.g. cross-compile note

    const sel = state.selected.has(tg.id) ? "sel" : "";
    return `<article class="cell ${kind} ${sel}" data-id="${tg.id}" style="animation-delay:${i * 28}ms">
      <div class="cell-top">
        <span class="cell-plat">${tg.platform}</span>
        <span class="led"></span>
      </div>
      <div class="cell-label">${esc(tg.label)}</div>
      <div class="cell-arch">${tg.arch} · .${tg.ext}</div>
      <div class="cell-note">${esc(tg.note || "")}</div>
      ${reason ? `<div class="cell-reason">${esc(reason)}</div>` : ""}
      <div class="cell-check"></div>
    </article>`;
  }).join("");

  $$(".cell.ready").forEach(c => c.addEventListener("click", () => toggleSel(c.dataset.id)));
  updateTray();
}

function toggleSel(id) {
  state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id);
  renderBoard();
}

function updateTray() {
  const n = state.selected.size;
  $("#sel-count").textContent = n;
  $("#btn-build").disabled = n === 0 || state.running;
  $("#btn-plan").disabled  = n === 0;
  const plats = [...new Set([...state.selected].map(id =>
    state.targets.find(t => t.id === id)?.platform))].filter(Boolean);
  $("#sel-hint").textContent = n ? `→ ${plats.join(", ")}` : "";
}

/* ── config form ──────────────────────────────────────── */
const PERMS = [
  ["enableKeyboard", "perm.enableKeyboard"], ["enableClipboard", "perm.enableClipboard"],
  ["enableFileTransfer", "perm.enableFileTransfer"], ["enableAudio", "perm.enableAudio"],
  ["enableTCP", "perm.enableTCP"], ["enableRemoteRestart", "perm.enableRemoteRestart"],
  ["enableRecording", "perm.enableRecording"], ["enableBlockingInput", "perm.enableBlockingInput"],
  ["enableRemoteModi", "perm.enableRemoteModi"], ["enablePrinter", "perm.enablePrinter"],
  ["enableCamera", "perm.enableCamera"], ["enableTerminal", "perm.enableTerminal"],
];
const FLAGS = [
  ["delayFix", "flag.delayFix"], ["hidecm", "flag.hidecm"],
  ["xOffline", "flag.xOffline"], ["removeNewVersionNotif", "flag.removeNewVersionNotif"],
  ["removeWallpaper", "flag.removeWallpaper"], ["denyLan", "flag.denyLan"],
  ["enableDirectIP", "flag.enableDirectIP"], ["autoClose", "flag.autoClose"],
];

function buildToggles() {
  $("#perm-toggles").innerHTML = PERMS.map(([k, l]) =>
    `<label class="tg"><input type="checkbox" data-key="${k}"><span>${t(l)}</span></label>`).join("");
  $("#flag-toggles").innerHTML = FLAGS.map(([k, l]) =>
    `<label class="tg"><input type="checkbox" data-key="${k}"><span>${t(l)}</span></label>`).join("");
}

function fillConfig(cfg) {
  state.config = cfg;
  $$("[data-key]").forEach(el => {
    const k = el.dataset.key;
    if (!(k in cfg)) return;
    if (el.type === "checkbox") el.checked = truthy(cfg[k]);
    else el.value = cfg[k] ?? "";
  });
  refreshPreview();
}

function collectConfig() {
  const cfg = { ...state.config };
  $$("[data-key]").forEach(el => {
    const k = el.dataset.key;
    if (el.type === "checkbox") cfg[k] = el.checked ? "on" : false;
    else cfg[k] = el.value;
  });
  return cfg;
}

const truthy = v => v === true || v === "on";

async function refreshPreview() {
  const cfg = collectConfig();
  const p = await api("/api/preview", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  try {
    $("#custom-preview").textContent = JSON.stringify(JSON.parse(p.custom_txt), null, 2);
  } catch { $("#custom-preview").textContent = p.custom_txt; }
  const e = p.env;
  $("#env-preview").textContent =
    `server : ${e.CUSTOM_SERVER}\nkey    : ${e.CUSTOM_KEY}\napi    : ${e.CUSTOM_API_SERVER}\n` +
    `app    : ${e.CUSTOM_APPNAME}\ncompany: ${e.CUSTOM_COMPNAME}\n` +
    `flags  : delayFix=${e.CUSTOM_DELAY_FIX} hidecm=${e.CUSTOM_HIDE_CM} ` +
    `xOffline=${e.CUSTOM_X_OFFLINE}`;
}

$("#btn-save-config").addEventListener("click", async () => {
  const cfg = collectConfig();
  const r = await api("/api/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  const note = $("#save-note");
  note.textContent = r.ok ? t("config.saved") : (t("config.saveError") + (r.error || "?"));
  note.style.color = r.ok ? "" : "var(--bad)";
  state.config = cfg;
  setTimeout(() => (note.textContent = ""), 2500);
});

document.addEventListener("input", e => {
  if (e.target.closest("#tab-config") && e.target.dataset.key) refreshPreview();
});

/* ── build console ────────────────────────────────────── */
const con = $("#console");
const MAX_DOM_LINES = 1500;      // cap DOM nodes so the tab stays responsive
const MAX_BUFFER_LINES = 40000;  // full log kept for the copy button
let logBuffer = [];              // complete (capped) log text for copying
let pending = [];                // lines waiting to be flushed to the DOM
let flushScheduled = false;

function lineClass(text) {
  if (text.startsWith("$ ")) return "con-cmd";
  if (text.startsWith("=== ") || text.startsWith("\n=== ")) return "con-head";
  if (/✓|artifact:|DONE/.test(text)) return "con-ok";
  if (/^\s*!!|FAILED|error/i.test(text)) return "con-err";
  if (/^\s*!|WARNING|warn/i.test(text)) return "con-warn";
  return "";
}

function flushConsole() {
  flushScheduled = false;
  if (!pending.length) return;
  const frag = document.createDocumentFragment();
  for (const text of pending) {
    const span = document.createElement("span");
    const cls = lineClass(text);
    if (cls) span.className = cls;
    span.textContent = text + "\n";
    frag.appendChild(span);
  }
  pending = [];
  const nearBottom = con.scrollHeight - con.scrollTop - con.clientHeight < 120;
  con.appendChild(frag);
  // trim old DOM nodes to keep the tab snappy
  while (con.childNodes.length > MAX_DOM_LINES) con.removeChild(con.firstChild);
  if (nearBottom) con.scrollTop = con.scrollHeight;  // stick to bottom unless scrolled up
}

function conLine(text) {
  logBuffer.push(text);
  if (logBuffer.length > MAX_BUFFER_LINES) logBuffer.shift();
  pending.push(text);
  if (!flushScheduled) { flushScheduled = true; requestAnimationFrame(flushConsole); }
}

function clearConsole() {
  con.innerHTML = ""; logBuffer = []; pending = [];
}

async function copyBuildLog(btn) {
  const text = logBuffer.join("\n");
  try {
    await navigator.clipboard.writeText(text);
    if (btn) { const o = btn.textContent; btn.textContent = t("build.copied"); setTimeout(() => btn.textContent = o, 1400); }
  } catch {
    // clipboard API can be blocked; fall back to a temporary textarea
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); } catch {}
    ta.remove();
    if (btn) { const o = btn.textContent; btn.textContent = t("build.copied"); setTimeout(() => btn.textContent = o, 1400); }
  }
}

let timerHandle = null, startedAt = 0;
function setStatus(s) {
  const el = $("#build-status");
  el.dataset.status = s;
  el.textContent = t("build." + s);
  el.className = "build-status " + (
    s === "running" ? "running" : s === "done" ? "done" : s === "failed" ? "failed" : "");
}
function startTimer() {
  startedAt = Date.now();
  timerHandle = setInterval(() => {
    const s = Math.floor((Date.now() - startedAt) / 1000);
    $("#build-timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 500);
}
function stopTimer() { clearInterval(timerHandle); }

function openStream() {
  const es = new EventSource("/api/build/stream");
  es.onmessage = ev => {
    try { conLine(JSON.parse(ev.data).line); } catch {}
  };
  es.addEventListener("done", () => { es.close(); onBuildEnd(); });
  es.onerror = () => { /* keep-alive gaps are normal; browser retries */ };
}

async function onBuildEnd() {
  stopTimer();
  state.running = false;
  $("#btn-cancel").disabled = true;
  const st = await api("/api/build/status");
  const r = st.result || {};
  setStatus(r.ok ? "done" : (r.cancelled ? "idle" : "failed"));
  renderArtifacts(r.artifacts || []);
  updateTray();
}

function renderArtifacts(list) {
  $("#artifacts").innerHTML = list.map(a =>
    `<div class="artifact">${esc(a)}</div>`).join("");
}

$("#btn-copy-log").addEventListener("click", (e) => copyBuildLog(e.target));
$("#btn-build").addEventListener("click", () => startBuild(false));
$("#btn-plan").addEventListener("click", () => startBuild(true));
$("#btn-cancel").addEventListener("click", () =>
  api("/api/build/cancel", { method: "POST" }));

async function startBuild(dry) {
  if (state.selected.size === 0) return;
  // jump to console tab
  $$(".tab").forEach(x => x.classList.remove("is-active"));
  $$(".panel").forEach(x => x.classList.remove("is-active"));
  $('.tab[data-tab="console"]').classList.add("is-active");
  $("#tab-console").classList.add("is-active");

  clearConsole();
  renderArtifacts([]);
  const payload = {
    version: $("#version").value.trim() || "latest",
    targets: [...state.selected],
    dry_run: dry || $("#dry-run").checked,
  };

  // preflight (non-dry): warn about missing tools but let the user proceed
  if (!payload.dry_run) {
    const pf = await api("/api/build/preflight", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!pf.ok) {
      conLine(t("build.preflight"));
      pf.problems.forEach(p => conLine("    - " + p));
      conLine(t("build.preflightFix") + "\n");
    }
  }

  const r = await api("/api/build/start", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) { conLine("!! " + (r.message || r.error || "could not start")); return; }

  state.running = true;
  $("#btn-cancel").disabled = payload.dry_run;
  $("#btn-build").disabled = true;
  setStatus("running");
  startTimer();
  openStream();
}

/* ── util ─────────────────────────────────────────────── */
function esc(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* ── boot ─────────────────────────────────────────────── */
function renderMatrixLede() {
  const m = state.matrix;
  if (!m) return;
  const ready = m.targets.filter(x => x.ready).length;
  const buildable = m.targets.filter(x => x.buildable).length;
  $("#matrix-lede").textContent = t("targets.ledeDynamic",
    { os: m.host.os, n: buildable, ready });
}

async function loadMatrix() {
  const m = await api("/api/matrix");
  state.matrix = m;
  renderSpec(m.host);
  state.targets = m.targets;
  renderBoard();
  renderMatrixLede();
}

async function boot() {
  buildToggles();
  await loadToolchains();
  await Promise.all([
    loadMatrix(),
    api("/api/prereqs").then(renderPrereqs),
    api("/api/config").then(fillConfig),
  ]);
}
$("#recheck").addEventListener("click", async () => {
  $("#prereqs").innerHTML = `<li class="muted">${t("rescanning")}</li>`;
  await loadToolchains();
  await api("/api/prereqs").then(renderPrereqs);
  await loadMatrix();
});

/* ── i18n: re-render dynamic parts when the language flips ─ */
window.__i18nRerender = () => {
  if (state.host) renderSpec(state.host);
  if (state.prereqs) renderPrereqs(state.prereqs);
  if (state.targets.length) { buildToggles(); renderBoard(); }
  renderMatrixLede();
  const st = $("#build-status");
  if (st.dataset.status) setStatus(st.dataset.status);
  if (state.config) fillConfig(state.config);
};

boot();
