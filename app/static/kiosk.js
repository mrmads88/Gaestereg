(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pad = (n) => (n < 10 ? "0" : "") + n;
const hhmm = (d) => pad(d.getHours()) + ":" + pad(d.getMinutes());
const initials = (n) => String(n || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
const first = (n) => String(n || "").split(" ")[0];

const TOKEN = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
const PREVIEW = new URLSearchParams(location.search).has("preview");
const API = "/api/kiosk/" + encodeURIComponent(TOKEN);

const T = {
  da: {
    wallSub: "Tryk på den, du skal besøge. Så giver vi besked.", wallHint: "Tryk på skærmen for at begynde",
    qHost: "Hvem skal du besøge?", leadHost: "Tryk på personen.", checkOut: "Tjek ud", back: "Tilbage",
    searchP: "Søg på navn", any: "Ved ikke hvem", anySub: "Receptionen hjælper dig",
    qName: "Hvem er du?", nameLead: "Så ved de, hvem der venter.", lName: "Dit fulde navn", lPhone: "Dit mobilnummer",
    lCompany: "Dit firma", optional: "(valgfrit)", checkIn: "Tjek ind", visiting: "Du besøger",
    consent: "Vi gemmer dine oplysninger og tidspunktet af hensyn til sikkerhed og evakuering. De slettes efter {d} dage.",
    hi: "Velkommen", notified: "{h} har fået besked og kommer ud til dig. Tag gerne plads imens.",
    notifiedRec: "Receptionen har fået besked og hjælper dig om lidt.", printing: "Dit gæstekort printes nu", finish: "Færdig",
    qOut: "Tryk på dit navn", noGuests: "Der er ingen tjekket ind lige nu.", inAt: "Ind kl.", bye: "Tak for besøget",
    byeSub: "Du er tjekket ud. Aflevér gerne dit gæstekort.", errTitle: "Skærmen er ikke sat op",
    errBody: "Linket er ikke gyldigt længere. Kontakt den, der har sat skærmen op.", noHit: "Ingen fundet.",
    guest: "GÆST", visitingL: "Besøger", date: "Dato", phName: "Dit navn", phCo: "Dit firma", space: "mellemrum",
    stepOf: "Trin {a} af {b}", sHost: "Vælg person", sName: "Om dig", ready: "Du er tjekket ind",
    errNet: "Der er ingen forbindelse. Prøv igen om lidt.", reception: "Receptionen",
    chooseLang: "Vælg sprog", welcomeTo: "Velkommen til {n}",
  },
  en: {
    wallSub: "Tap the person you're visiting and we'll let them know.", wallHint: "Tap the screen to begin",
    qHost: "Who are you visiting?", leadHost: "Tap the person.", checkOut: "Check out", back: "Back",
    searchP: "Search by name", any: "Not sure who", anySub: "Reception will help you",
    qName: "Who are you?", nameLead: "So they know who is waiting.", lName: "Your full name", lPhone: "Your mobile number",
    lCompany: "Your company", optional: "(optional)", checkIn: "Check in", visiting: "You're visiting",
    consent: "We store your details and the time for safety and evacuation. They're deleted after {d} days.",
    hi: "Welcome", notified: "{h} has been notified and will come and meet you. Please take a seat.",
    notifiedRec: "Reception has been notified and will be with you shortly.", printing: "Your visitor badge is printing", finish: "Done",
    qOut: "Tap your name", noGuests: "Nobody is checked in right now.", inAt: "In at", bye: "Thanks for visiting",
    byeSub: "You're checked out. Please return your badge.", errTitle: "This screen isn't set up",
    errBody: "The link is no longer valid. Contact whoever set up this screen.", noHit: "No match.",
    guest: "VISITOR", visitingL: "Visiting", date: "Date", phName: "Your name", phCo: "Your company", space: "space",
    stepOf: "Step {a} of {b}", sHost: "Choose person", sName: "About you", ready: "You're checked in",
    errNet: "No connection. Please try again shortly.", reception: "Reception",
    chooseLang: "Choose language", welcomeTo: "Welcome to {n}",
  },
};
let lang = "da";
const t = (k) => (T[lang] || T.da)[k] || k;
// Sprog: kundens valgte sprog, som både har tekster her og flag i langs.js.
const LANGS = () => ((CFG && CFG.languages) || ["da"]).filter((c) => T[c] && window.NODD_LANG && window.NODD_LANG(c));
const MODE = () => (LANGS().length < 2 ? "off" : (CFG && CFG.lang_mode) || "toggle");
const HOME = () => (MODE() === "first" ? "lang" : "start");
const flag = (c) => '<span class="flag">' + window.NODD_LANG(c).flag() + "</span>";
// Tilbage til start: kundens standardsprog og den første skærm (sprogvalg eller personer).
function home() {
  const d = CFG && LANGS().includes(CFG.lang_default) ? CFG.lang_default : LANGS()[0];
  if (lang !== d) { lang = d; applyLang(); }
  show(HOME());
}

let CFG = null, cur = "loading", visit = {}, lastAct = Date.now(), homeT, cfgSig = "";

// ---------- config ----------
async function loadConfig() {
  try {
    const r = await fetch(API + "/config", { cache: "no-store" });
    if (r.status === 404) { CFG = null; show("error"); return; }
    if (!r.ok) throw new Error(r.status);
    const cfg = await r.json();
    const sig = JSON.stringify(cfg);
    if (sig === cfgSig) return;
    cfgSig = sig; CFG = cfg;
    applyLook();
    if (["loading", "error", "start", "lang"].includes(cur)) home();
  } catch (e) {
    if (!CFG) { toast(t("errNet"), true); setTimeout(loadConfig, 5000); }
  }
}

function applyLook() {
  const r = document.documentElement;
  r.style.setProperty("--brand", CFG.color || "#1f3a5a");
  const bg = CFG.background_url;
  r.classList.toggle("has-photo", !!bg);
  r.classList.toggle("photo-wall", !!bg && CFG.background_scope === "wall");
  r.classList.toggle("photo-full", !!bg && CFG.background_scope === "full");
  r.style.setProperty("--photo", bg ? 'url("' + bg + '")' : "none");
  r.style.setProperty("--dim", ((CFG.background_dim || 0) / 100).toFixed(2));
  document.title = CFG.name;
  $("logoPlate").innerHTML = CFG.logo_url ? '<img src="' + esc(CFG.logo_url) + '" alt="' + esc(CFG.name) + '">' : '<span class="lname">' + esc(CFG.name) + "</span>";
  applyLang();
}

function applyLang() {
  document.querySelectorAll("[data-t]").forEach((el) => (el.textContent = t(el.dataset.t)));
  document.documentElement.lang = lang;
  if (!CFG) return;
  renderLangs();
  $("wWelcome").textContent = lang === "da" ? CFG.welcome_text : t("welcomeTo").replace("{n}", CFG.name);
  $("search").placeholder = t("searchP");
  $("consent").textContent = t("consent").replace("{d}", CFG.retention_days);
  tick();
  if (cur === "start") renderHosts();
  if (cur === "name") renderChosen();
  if (cur === "out") renderOut();
  if (["name", "done"].includes(cur)) { updateProgress(); updateBadge(); }
}
function renderLangs() {
  const langs = LANGS(), mode = MODE();
  $("langSw").hidden = mode === "off" || cur === "lang";
  $("langSw").innerHTML = langs.map((c) => '<button type="button" data-lang="' + c + '" aria-pressed="' + (c === lang) + '" aria-label="' +
    esc(window.NODD_LANG(c).native) + '">' + flag(c) + c.toUpperCase() + "</button>").join("");
  $("langQ").textContent = langs.map((c) => T[c].chooseLang).join(" · ");
  $("langList").innerHTML = langs.map((c) => { const L = window.NODD_LANG(c);
    return '<button class="langbtn" type="button" data-pick="' + c + '">' + flag(c) + "<b>" + esc(L.native) + "</b><span>" + esc(L.hello) + "</span></button>"; }).join("");
}
$("langSw").addEventListener("click", (e) => { const b = e.target.closest("[data-lang]"); if (!b) return; lang = b.dataset.lang; applyLang(); if (activeIn) renderOsk(); });
$("langList").addEventListener("click", (e) => { const b = e.target.closest("[data-pick]"); if (!b) return; lang = b.dataset.pick; applyLang(); show("start"); });

function tick() {
  const d = new Date();
  $("wClock").textContent = hhmm(d); $("nClock").textContent = hhmm(d);
  const L = window.NODD_LANG && window.NODD_LANG(lang);
  $("wDate").textContent = d.toLocaleDateString(L ? L.locale : "da-DK", { weekday: "long", day: "numeric", month: "long" });
}

// ---------- hosts ----------
const BELL = '<svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4"/></svg>';
function pic(h) { return h.photo_url ? '<img src="' + esc(h.photo_url) + '" alt="" loading="lazy">' : '<span class="ini">' + esc(initials(h.name)) + "</span>"; }
function renderHosts() {
  const all = CFG.hosts;
  const withPhotos = CFG.show_photos && all.some((h) => h.photo_url);
  $("searchWrap").hidden = all.length <= 12;
  const q = $("search").value.trim().toLowerCase();
  const list = all.filter((h) => !q || h.name.toLowerCase().includes(q) || (h.title || "").toLowerCase().includes(q));
  const n = list.length + (CFG.allow_unknown_host ? 1 : 0);
  const el = $("hosts");
  el.classList.toggle("compact", !withPhotos || all.length > 16);
  el.style.setProperty("--cols", n <= 2 ? 2 : n <= 6 ? 3 : 4);
  let html = list.map((h) => '<button class="host" type="button" data-host="' + h.id + '"><span class="pic">' + pic(h) + '</span><span class="tx"><b>' + esc(h.name) + "</b><span>" + esc(h.title || "") + "</span></span></button>").join("");
  if (!list.length) html = '<p class="empty">' + t("noHit") + "</p>";
  if (CFG.allow_unknown_host) html += '<button class="host any" type="button" data-host="any"><span class="pic">' + BELL + '</span><span class="tx"><b>' + t("any") + "</b><span>" + t("anySub") + "</span></span></button>";
  el.innerHTML = html;
}
$("search").addEventListener("input", renderHosts);
$("hosts").addEventListener("click", (e) => {
  const b = e.target.closest("[data-host]"); if (!b) return;
  const id = b.dataset.host;
  const host = id === "any" ? null : CFG.hosts.find((h) => String(h.id) === id);
  visit = { host, in: hhmm(new Date()) };
  show("name");
});
function renderChosen() {
  const h = visit.host;
  $("chosen").innerHTML = h
    ? '<span class="pic">' + (h.photo_url ? '<img src="' + esc(h.photo_url) + '" alt="">' : esc(initials(h.name))) + '</span><div><small>' + t("visiting") + "</small><b>" + esc(h.name) + "</b> <span>" + esc(h.title || "") + "</span></div>"
    : '<span class="pic">' + BELL + '</span><div><small>' + t("visiting") + "</small><b>" + t("reception") + "</b></div>";
}

// ---------- progress + badge ----------
function updateProgress() {
  const steps = ["sHost", "sName"];
  const idx = cur === "name" ? 1 : 2;
  $("segs").innerHTML = steps.map((s, i) => '<i class="' + (i < idx ? "done" : i === idx ? "cur" : "") + '"></i>').join("");
  $("progL").textContent = cur === "done" ? t("ready") : t("stepOf").replace("{a}", idx + 1).replace("{b}", steps.length) + " · " + t(steps[idx]);
}
function badgeHTML(g, live) {
  const d = new Date();
  const name = g.name ? esc(g.name) : live ? '<span class="ph">' + t("phName") + "</span>" : "";
  const co = g.company ? esc(g.company) : live && CFG.ask_company ? '<span class="ph">' + t("phCo") + "</span>" : "";
  const logo = CFG.logo_url ? '<img src="' + esc(CFG.logo_url) + '" alt="">' : "<span>" + esc(CFG.name) + "</span>";
  return '<div class="badge"><div class="b-band"><span class="b-logo">' + logo + '</span><span class="b-kind">' + t("guest") + "</span></div>" +
    '<div class="b-body"><span class="b-name">' + name + '</span><span class="b-co">' + co + "</span>" +
    '<div class="b-grid"><div><small>' + t("visitingL") + "</small><b>" + esc(g.host || t("reception")) + "</b></div><div><small>" + t("date") + '</small><b class="mono">' + pad(d.getDate()) + "." + pad(d.getMonth() + 1) + " · " + esc(g.time || hhmm(d)) + "</b></div></div></div>" +
    '<div class="b-foot"><span>' + esc(CFG.name) + '</span><span class="mono">' + esc(g.no || "") + "</span></div></div>";
}
function updateBadge() {
  const g = { host: visit.host ? visit.host.name : "", time: visit.in, no: visit.no };
  if (cur === "name") { g.name = $("fName").value.trim(); g.company = $("fCompany").value.trim(); }
  else { g.name = visit.name; g.company = visit.company; }
  $("liveBadge").innerHTML = badgeHTML(g, cur === "name");
}

// ---------- navigation ----------
let stack = [];
function show(id, push) {
  cur = id;
  document.querySelectorAll("main .screen").forEach((s) => (s.hidden = s.id !== "s-" + id));
  if (id === "start" || id === "lang") { stack = []; visit = {}; $("search").value = ""; }
  else if (push !== false && !["loading", "error"].includes(id)) stack.push(id);
  const flow = id === "name" || id === "done";
  $("wallIdle").hidden = flow; $("wallFlow").hidden = !flow;
  $("wallHint").style.visibility = flow ? "hidden" : "visible";
  // På sprogskærmen står flagene midt på skærmen. Så er de små i hjørnet overflødige.
  $("langSw").hidden = MODE() === "off" || id === "lang";
  if (flow) { updateProgress(); updateBadge(); }
  $("hang").classList.toggle("issued", id === "done");
  hideOsk();
  const scr = $("s-" + id); if (scr) scr.scrollTop = 0;
  if (id === "start") renderHosts();
  if (id === "name") prepName();
  if (id === "out") renderOut();
}
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-go]"); if (g) { show(g.dataset.go); return; }
  if (e.target.closest("[data-back]")) { stack.pop(); const to = stack.pop(); show(to || "start"); return; }
  if (e.target.closest("[data-home]")) home();
});

// ---------- name step ----------
function prepName() {
  renderChosen();
  $("flPhone").hidden = !CFG.ask_phone;
  $("flCompany").hidden = !CFG.ask_company;
  $("nameOpt").hidden = CFG.name_required;
  $("phoneOpt").hidden = CFG.phone_required;
  if (!visit.name) { $("fName").value = ""; $("fPhone").value = ""; $("fCompany").value = ""; }
  validate(); updateBadge();
}
function digits(s) { return (s || "").replace(/\D/g, ""); }
function validate() {
  const okName = !CFG.name_required || $("fName").value.trim().length >= 2;
  const okPhone = !CFG.ask_phone || !CFG.phone_required || digits($("fPhone").value).length >= 8;
  $("checkinBtn").disabled = !(okName && okPhone);
}
["fName", "fPhone", "fCompany"].forEach((id) => $(id).addEventListener("input", () => { validate(); updateBadge(); }));

let busy = false;
$("nameForm").addEventListener("submit", async (e) => {
  e.preventDefault(); if ($("checkinBtn").disabled || busy) return;
  busy = true; $("checkinBtn").disabled = true;
  const body = { host_id: visit.host ? visit.host.id : null, guest_name: $("fName").value.trim(),
    guest_phone: CFG.ask_phone ? $("fPhone").value.trim() : "", guest_company: CFG.ask_company ? $("fCompany").value.trim() : "", preview: PREVIEW };
  try {
    const r = await fetch(API + "/checkin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { toast(data.detail && typeof data.detail === "string" ? data.detail : t("errNet"), true); if (r.status === 404) loadConfig(); return; }
    visit.name = data.guest_name; visit.company = body.guest_company; visit.no = data.badge_no; visit.in = data.time;
    const f = first(visit.name);
    $("doneTitle").textContent = t("hi") + (f ? ", " + f : "");
    $("doneSub").textContent = visit.host ? t("notified").replace("{h}", first(visit.host.name)) : t("notifiedRec");
    $("printNote").hidden = !CFG.print_badge;
    const g = { name: visit.name, company: visit.company, host: visit.host ? visit.host.name : "", time: visit.in, no: visit.no };
    $("inlineBadge").innerHTML = badgeHTML(g, false);
    show("done"); restartTimer("doneTimer");
    if (CFG.print_badge && !PREVIEW) printBadge(g);
    clearTimeout(homeT); homeT = setTimeout(() => { if (cur === "done") home(); }, 10000);
  } catch (err) {
    toast(t("errNet"), true);
  } finally { busy = false; validate(); }
});

// ---------- check out ----------
async function renderOut() {
  $("outRows").innerHTML = "";
  try {
    const r = await fetch(API + "/inside", { cache: "no-store" });
    const list = r.ok ? await r.json() : [];
    $("outRows").innerHTML = list.map((g) => '<button class="rowbtn" type="button" data-out="' + g.id + '" data-name="' + esc(g.name) + '"><span class="av">' + esc(initials(g.name)) + '</span><span class="tx"><b>' + esc(g.name) + "</b><span>" + esc(g.host_name) + " · " + t("inAt") + " " + esc(g.time) + '</span></span><span class="pill-out">' + t("checkOut") + "</span></button>").join("") || '<p class="empty">' + t("noGuests") + "</p>";
  } catch (e) { toast(t("errNet"), true); }
}
$("outRows").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-out]"); if (!b) return;
  if (!PREVIEW) {
    try { await fetch(API + "/checkout/" + b.dataset.out, { method: "POST" }); } catch (err) { toast(t("errNet"), true); return; }
  }
  $("byeTitle").textContent = t("bye") + ", " + first(b.dataset.name);
  show("bye"); restartTimer("byeTimer");
  clearTimeout(homeT); homeT = setTimeout(() => { if (cur === "bye") home(); }, 5000);
});

function restartTimer(id) { const el = $(id), i = el.firstElementChild; el.replaceChild(i.cloneNode(), i); }

// ---------- print ----------
const SIZES = { "62x100": "62mm 100mm", "54x86": "86mm 54mm", a6: "A6" };
function printBadge(g) {
  $("pageSize").textContent = "@media print{@page{size:" + (SIZES[CFG.badge_size] || "auto") + ";margin:0}}";
  $("printArea").innerHTML = badgeHTML(g, false);
  setTimeout(() => { try { window.print(); } catch (e) {} }, 500);
}

// ---------- on-screen keyboard ----------
const ROWS = [["1","2","3","4","5","6","7","8","9","0"],["q","w","e","r","t","y","u","i","o","p","å"],["a","s","d","f","g","h","j","k","l","æ","ø"],["⇧","z","x","c","v","b","n","m","-","⌫"],["@",".","space","OK"]];
const NUM = [["1","2","3"],["4","5","6"],["7","8","9"],["+","0","⌫"],["OK"]];
let shift = true, activeIn = null;
const useOsk = () => !matchMedia("(hover: hover) and (pointer: fine)").matches || PREVIEW || new URLSearchParams(location.search).has("osk");
function renderOsk() {
  const num = activeIn && activeIn.hasAttribute("data-num");
  $("osk").classList.toggle("num", !!num);
  $("osk").innerHTML = (num ? NUM : ROWS).map((r) => '<div class="r">' + r.map((k) => {
    const cls = k === "⇧" || k === "⌫" ? "fn" : k === "space" ? "sp" : k === "OK" ? "ok" : "";
    const label = k === "space" ? t("space") : k.length === 1 && shift && !num ? k.toUpperCase() : k;
    return '<button type="button" class="' + cls + '" data-k="' + k + '" aria-label="' + label + '">' + label + "</button>";
  }).join("") + "</div>").join("");
}
function hideOsk() { $("osk").hidden = true; activeIn = null; }
document.addEventListener("focusin", (e) => {
  const el = e.target;
  if (!el.classList || !el.classList.contains("osk-in")) return;
  if (!useOsk()) { el.setAttribute("inputmode", el.hasAttribute("data-num") ? "tel" : "text"); return; }
  el.setAttribute("inputmode", "none");
  activeIn = el; shift = !el.value || /[\s-]$/.test(el.value); renderOsk(); $("osk").hidden = false;
  setTimeout(() => activeIn && activeIn.scrollIntoView({ block: "center", behavior: "smooth" }), 60);
});
document.addEventListener("focusout", () => setTimeout(() => { const a = document.activeElement; if (!a || !a.classList || !a.classList.contains("osk-in")) hideOsk(); }, 0));
$("osk").addEventListener("pointerdown", (e) => e.preventDefault());
$("osk").addEventListener("click", (e) => {
  const b = e.target.closest("[data-k]"); if (!b || !activeIn) return;
  const k = b.dataset.k; let v = activeIn.value;
  const num = activeIn.hasAttribute("data-num");
  if (k === "⌫") v = v.slice(0, -1);
  else if (k === "⇧") { shift = !shift; renderOsk(); return; }
  else if (k === "OK") {
    const next = activeIn.id === "fName" && !$("flPhone").hidden ? $("fPhone") : activeIn.id !== "fCompany" && !$("flCompany").hidden && activeIn.id !== "search" ? $("fCompany") : null;
    activeIn.blur(); hideOsk(); if (next && !next.value) next.focus(); return;
  }
  else if (k === "space") v += " ";
  else v += k.length === 1 && shift && !num ? k.toUpperCase() : k;
  activeIn.value = v; activeIn.dispatchEvent(new Event("input", { bubbles: true }));
  if (!num) { const ns = !v || /[\s-]$/.test(v); if (ns !== shift) { shift = ns; renderOsk(); } }
});

// ---------- idle + refresh ----------
["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, () => (lastAct = Date.now()), true));
setInterval(() => {
  tick();
  // Efter en pause: tilbage til start og standardsproget, så næste gæst ikke møder den forriges sprog.
  const atHome = cur === HOME() && lang === (LANGS().includes(CFG && CFG.lang_default) ? CFG.lang_default : LANGS()[0]);
  if (CFG && !["loading", "error"].includes(cur) && !atHome && Date.now() - lastAct > (CFG.idle_seconds || 60) * 1000) home();
}, 1000);
setInterval(() => { if (["start", "lang", "error"].includes(cur)) loadConfig(); }, 60000);
window.addEventListener("message", (e) => { if (e.origin === location.origin && e.data === "reload-config") { cfgSig = ""; loadConfig(); } });

let toastT;
function toast(m, err) { const x = $("toast"); x.textContent = m; x.classList.toggle("err", !!err); x.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (x.hidden = true), 3200); }

$("previewTag").hidden = !PREVIEW;
applyLang();
tick();
loadConfig();
try { navigator.wakeLock && navigator.wakeLock.request("screen").catch(() => {}); } catch (e) {}
})();
