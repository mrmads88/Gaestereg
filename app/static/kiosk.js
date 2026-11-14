(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pad = (n) => (n < 10 ? "0" : "") + n;
const hhmm = (d) => pad(d.getHours()) + ":" + pad(d.getMinutes());
const initials = (n) => String(n || "?").split(/\s+/).filter((w) => /^[\p{L}\p{N}]/u.test(w)).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
const first = (n) => String(n || "").split(" ")[0];

const TOKEN = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
const PREVIEW = new URLSearchParams(location.search).has("preview");
// ?m=1: gæstens egen telefon (fra QR-plakaten ved døren). Telefonens eget tastatur, ingen print.
const MOBILE = new URLSearchParams(location.search).has("m");
const API = "/api/kiosk/" + encodeURIComponent(TOKEN);

const T = {
  da: {
    wallSub: "Tryk på den, du skal besøge. Så giver vi besked.", wallHint: "Tryk på skærmen for at begynde", privacy: "Privatliv",
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
    pkg: "Pakke", pkgQ: "Hvem er pakken til?", pkgLead: "Tryk på modtageren.", pkgAny: "Godsmodtagelsen",
    pkgAnySub: "Hvis du ikke ved hvem", pkgFrom: "Fra hvilket firma?", pkgName: "Dit navn", pkgSend: "Giv besked",
    pkgDone: "Tak for pakken", pkgDoneSub: "{h} har fået besked.", pkgTo: "Pakke til",
    addGuest: "Tilføj gæst", guestN: "Gæst {n}", remove: "Fjern", accept: "Jeg har læst og accepterer {x}",
    read: "Læs", acceptBtn: "Accepter", close: "Luk", wifi: "WiFi", wifiPw: "Kode",
    closedTitle: "Vi har lukket", closedSub: "Kom gerne igen inden for åbningstiden.", hoursToday: "Åbent i dag",
    closedToday: "Lukket i dag", replyWait: "Venter på svar fra {h}", reply_now: "{h} er på vej ud til dig",
    reply_5: "{h} kommer om 5 minutter", reply_10: "{h} kommer om 10 minutter",
    reply_reception: "Receptionen tager imod dig", guestsHi: "Velkommen, {n}", and: "og",
    haveCode: "Jeg har en kode", codeQ: "Tast din kode", codeLead: "Du har fået den på SMS eller mail.",
    scan: "Scan QR-kode", scanStop: "Stop kamera", codeBad: "Koden passer ikke. Tjek den, eller vælg personen i stedet.",
    clear: "Ryd",
    qFirm: "Hvilket firma skal du besøge?", leadFirm: "Tryk på firmaet, eller søg efter personen.", allFirms: "Alle firmaer",
    searchAll: "Søg på firma eller person", firmReception: "Firmaets modtagelse", houseReception: "Husets reception",
  },
  en: {
    wallSub: "Tap the person you're visiting and we'll let them know.", wallHint: "Tap the screen to begin", privacy: "Privacy",
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
    pkg: "Delivery", pkgQ: "Who is the delivery for?", pkgLead: "Tap the recipient.", pkgAny: "Goods reception",
    pkgAnySub: "If you're not sure who", pkgFrom: "Which company are you from?", pkgName: "Your name", pkgSend: "Notify",
    pkgDone: "Thanks for the delivery", pkgDoneSub: "{h} has been notified.", pkgTo: "Delivery for",
    addGuest: "Add guest", guestN: "Guest {n}", remove: "Remove", accept: "I have read and accept {x}",
    read: "Read", acceptBtn: "Accept", close: "Close", wifi: "Wi-Fi", wifiPw: "Password",
    closedTitle: "We're closed", closedSub: "Please come back during opening hours.", hoursToday: "Open today",
    closedToday: "Closed today", replyWait: "Waiting for {h} to reply", reply_now: "{h} is on the way to meet you",
    reply_5: "{h} will be here in 5 minutes", reply_10: "{h} will be here in 10 minutes",
    reply_reception: "Reception will help you", guestsHi: "Welcome, {n}", and: "and",
    haveCode: "I have a code", codeQ: "Enter your code", codeLead: "You received it by text message or email.",
    scan: "Scan QR code", scanStop: "Stop camera", codeBad: "That code doesn't match. Check it, or choose the person instead.",
    clear: "Clear",
    qFirm: "Which company are you visiting?", leadFirm: "Tap the company, or search for the person.", allFirms: "All companies",
    searchAll: "Search company or person", firmReception: "Company reception", houseReception: "Building reception",
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
// Husets skærm (kontorhotel): gæsten vælger først firma. FIRM er det valgte firma, ellers null.
let FIRM = null, pkgFirm = null;
const curHosts = () => (FIRM ? FIRM.hosts : CFG.hosts);
const allowUnknown = () => (FIRM ? FIRM.allow_unknown_host : CFG.allow_unknown_host);
const firmById = (id) => (CFG.firms || []).find((f) => f.id === id) || null;
function home() {
  FIRM = null; pkgFirm = null;
  $("privOv").hidden = true;
  const d = CFG && LANGS().includes(CFG.lang_default) ? CFG.lang_default : LANGS()[0];
  if (lang !== d) { lang = d; applyLang(); }
  show(isOpen() ? HOME() : "closed");
}
// Åbningstider: 7 dage (mandag først), hver [åbner, lukker] eller null. Tom liste = altid åben.
// Forhåndsvisningen i admin ignorerer åbningstider, så man kan rette skærmen om aftenen.
function isOpen(d) {
  const h = CFG && CFG.opening_hours;
  if (PREVIEW || !h || h.length !== 7) return true;
  d = d || new Date();
  const day = h[(d.getDay() + 6) % 7];
  if (!day) return false;
  const m = pad(d.getHours()) + ":" + pad(d.getMinutes());
  return m >= day[0] && m < day[1];
}
function renderClosed() {
  $("closedText").textContent = CFG.closed_text || t("closedSub");
  const today = CFG.opening_hours && CFG.opening_hours[(new Date().getDay() + 6) % 7];
  $("closedHours").textContent = today ? t("hoursToday") + " " + today[0] + "–" + today[1] : t("closedToday");
}

let CFG = null, cur = "loading", visit = {}, lastAct = Date.now(), homeT, cfgSig = "";

// ---------- config ----------
async function loadConfig() {
  try {
    const r = await fetch(API + "/config" + (PREVIEW ? "?pv=1" : MOBILE ? "?m=1" : ""), { cache: "no-store" });
    if (r.status === 404) { CFG = null; show("error"); return; }
    if (!r.ok) throw new Error(r.status);
    const cfg = await r.json();
    const sig = JSON.stringify(cfg);
    if (sig === cfgSig) return;
    cfgSig = sig; CFG = cfg;
    applyLook();
    if (["loading", "error", "start", "lang", "closed"].includes(cur)) home();
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
  if (cur === "closed") renderClosed();
  if (cur === "pkg") renderPkg();
  if (cur === "pkg2") renderPkgChosen();
  if (cur === "name") { renderChosen(); renderExtras(); renderTerms(); }
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
function firmLogo(f) { return f.logo_url ? '<img src="' + esc(f.logo_url) + '" alt="">' : '<span class="ini">' + esc(initials(f.name)) + "</span>"; }
function renderFirms() {
  const el = $("hosts"), q = $("search").value.trim().toLowerCase();
  $("startQ").textContent = t("qFirm"); $("startLead").textContent = t("leadFirm"); $("firmBack").hidden = true;
  $("searchWrap").hidden = false; $("search").placeholder = t("searchAll");
  el.classList.remove("compact");
  if (q) {  // søg på tværs af firmaer: både firmanavne og personer
    const firms = CFG.firms.filter((f) => f.name.toLowerCase().includes(q));
    const people = [];
    CFG.firms.forEach((f) => f.hosts.forEach((h) => { if (h.name.toLowerCase().includes(q) || (h.title || "").toLowerCase().includes(q)) people.push([f, h]); }));
    el.classList.add("compact"); el.style.setProperty("--cols", 3);
    el.innerHTML = firms.map((f) => '<button class="host firm" type="button" data-firm="' + f.id + '"><span class="pic">' + firmLogo(f) + '</span><span class="tx"><b>' + esc(f.name) + "</b><span>" + f.hosts.length + "</span></span></button>").join("") +
      people.map(([f, h]) => '<button class="host" type="button" data-firm="' + f.id + '" data-host="' + h.id + '"><span class="pic">' + pic(h) + '</span><span class="tx"><b>' + esc(h.name) + "</b><span>" + esc(f.name) + (h.title ? " · " + esc(h.title) : "") + "</span></span></button>").join("") ||
      '<p class="empty">' + t("noHit") + "</p>";
    return;
  }
  const n = CFG.firms.length;
  el.style.setProperty("--cols", n <= 2 ? 2 : n <= 12 ? 3 : 4);
  el.innerHTML = CFG.firms.map((f) => '<button class="host firm" type="button" data-firm="' + f.id + '"><span class="pic">' + firmLogo(f) + '</span><span class="tx"><b>' + esc(f.name) + "</b></span></button>").join("");
}
// Pakke-knappen starter forfra med firmavalget. Tilbage fra næste skærm husker firmaet.
$("pkgBtn").addEventListener("click", () => { pkgFirm = null; });
$("firmBack").addEventListener("click", () => { FIRM = null; $("search").value = ""; renderHosts(); });

function renderHosts() {
  $("pkgBtn").hidden = !CFG.delivery_enabled;
  if (CFG.house && !FIRM) return renderFirms();
  $("startQ").textContent = t("qHost"); $("startLead").textContent = FIRM ? FIRM.name : t("leadHost");
  $("firmBack").hidden = !(CFG.house && FIRM); $("search").placeholder = t("searchP");
  const all = curHosts();
  const withPhotos = CFG.show_photos && all.some((h) => h.photo_url);
  $("searchWrap").hidden = all.length <= 12;
  const q = $("search").value.trim().toLowerCase();
  const list = all.filter((h) => !q || h.name.toLowerCase().includes(q) || (h.title || "").toLowerCase().includes(q));
  const n = list.length + (allowUnknown() ? 1 : 0);
  const el = $("hosts");
  el.classList.toggle("compact", !withPhotos || all.length > 16);
  el.style.setProperty("--cols", n <= 2 ? 2 : n <= 6 ? 3 : 4);
  let html = list.map((h) => '<button class="host" type="button" data-host="' + h.id + '"><span class="pic">' + pic(h) + '</span><span class="tx"><b>' + esc(h.name) + "</b><span>" + esc(h.title || "") + "</span></span></button>").join("");
  if (!list.length) html = '<p class="empty">' + t("noHit") + "</p>";
  if (allowUnknown()) html += '<button class="host any" type="button" data-host="any"><span class="pic">' + BELL + '</span><span class="tx"><b>' + t("any") + "</b><span>" + t("anySub") + "</span></span></button>";
  el.innerHTML = html;
}
$("search").addEventListener("input", renderHosts);
$("hosts").addEventListener("click", (e) => {
  const fb = e.target.closest("[data-firm]");
  if (fb && !FIRM) { FIRM = firmById(+fb.dataset.firm); $("search").value = ""; if (!fb.dataset.host) { renderHosts(); $("s-start").scrollTop = 0; return; } }
  const b = e.target.closest("[data-host]"); if (!b) return;
  const id = b.dataset.host;
  const host = id === "any" ? null : curHosts().find((h) => String(h.id) === id);
  visit = { host, in: hhmm(new Date()) };
  show("name");
});
function renderChosen() {
  const h = visit.host;
  $("chosen").innerHTML = h
    ? '<span class="pic">' + (h.photo_url ? '<img src="' + esc(h.photo_url) + '" alt="">' : esc(initials(h.name))) + '</span><div><small>' + t("visiting") + "</small><b>" + esc(h.name) + "</b> <span>" + esc(h.title || "") + "</span></div>"
    : '<span class="pic">' + BELL + '</span><div><small>' + t("visiting") + "</small><b>" + t("reception") + "</b></div>";
  if (FIRM) $("chosen").querySelector("div").insertAdjacentHTML("beforeend", '<span class="firmname">' + esc(FIRM.name) + "</span>");
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
    '<div class="b-grid"><div><small>' + t("visitingL") + "</small><b>" + esc(g.host || t("reception")) + "</b></div><div><small>" + t("date") + '</small><b class="mono">' + pad(d.getDate()) + "." + pad(d.getMonth() + 1) + " · " + esc(g.time || hhmm(d)) + "</b></div></div>" +
    (CFG.wifi_name ? '<div class="b-wifi">' + t("wifi") + ": " + esc(CFG.wifi_name) + (CFG.wifi_password ? " · " + t("wifiPw") + ": " + esc(CFG.wifi_password) : "") + "</div>" : "") +
    "</div>" + '<div class="b-foot"><span>' + esc(CFG.name) + '</span><span class="mono">' + esc(g.no || "") + "</span></div></div>";
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
  if (id === "start" || id === "lang" || id === "closed") { stack = []; visit = {}; $("search").value = ""; extras = []; termsOk(false); }
  else if (push !== false && !["loading", "error"].includes(id)) stack.push(id);
  const flow = id === "name" || id === "done";
  $("wallIdle").hidden = flow; $("wallFlow").hidden = !flow;
  $("wallHint").style.visibility = flow || id === "closed" ? "hidden" : "visible";
  // På sprogskærmen står flagene midt på skærmen. Så er de små i hjørnet overflødige.
  $("langSw").hidden = MODE() === "off" || id === "lang";
  if (flow) { updateProgress(); updateBadge(); }
  $("hang").classList.toggle("issued", id === "done");
  hideOsk();
  const scr = $("s-" + id); if (scr) scr.scrollTop = 0;
  if (id === "start") renderHosts();
  if (id === "name") prepName();
  if (id === "out") renderOut();
  if (id === "pkg") renderPkg();
  if (id === "pkg2") { renderPkgChosen(); $("pCompany").value = ""; $("pName").value = ""; }
  if (id === "closed") renderClosed();
  if (id === "code") { codeVal = ""; renderCode(); $("codeErr").hidden = true; $("scanBtn").hidden = !canScan(); }
  if (id !== "code") stopScan();
  if (id !== "done") stopReplyPoll();
}
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-go]"); if (g) { show(g.dataset.go); return; }
  if (e.target.closest("[data-back]")) { stack.pop(); const to = stack.pop(); show(to || "start"); return; }
  if (e.target.closest("[data-home]")) home();
});

// ---------- name step ----------
// ---------- flere gæster ----------
let extras = [];
function renderExtras() {
  $("extras").hidden = !CFG.group_checkin;
  if (!CFG.group_checkin) return;
  $("extraList").innerHTML = extras.length ? '<div class="group">' + extras.map((v, i) =>
    '<div class="fl"><div><label for="xg' + i + '">' + esc(t("guestN").replace("{n}", i + 2)) + '</label><input class="osk-in" id="xg' + i + '" data-x="' + i + '" maxlength="120" value="' + esc(v) + '"></div>' +
    '<button type="button" class="rm" data-rm="' + i + '" aria-label="' + esc(t("remove")) + '"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>').join("") + "</div>" : "";
  $("addGuest").hidden = extras.length >= 9;
}
$("addGuest").addEventListener("click", () => { extras.push(""); renderExtras(); const el = $("xg" + (extras.length - 1)); if (el) el.focus(); });
$("extraList").addEventListener("input", (e) => { const i = e.target.dataset.x; if (i != null) extras[+i] = e.target.value; });
$("extraList").addEventListener("click", (e) => { const b = e.target.closest("[data-rm]"); if (!b) return; extras.splice(+b.dataset.rm, 1); renderExtras(); });

// ---------- husregler ----------
function termsOk(v) { $("termsOk").checked = !!v; }
function renderTerms() {
  $("termsRow").hidden = !CFG.terms_enabled;
  $("termsLabel").textContent = t("accept").replace("{x}", CFG.terms_title || "husreglerne");
  $("termsRead").hidden = !CFG.terms_text;
}
$("termsOk").addEventListener("change", validate);
$("termsRead").addEventListener("click", () => {
  $("termsTitle").textContent = CFG.terms_title || ""; $("termsText").textContent = CFG.terms_text || "";
  $("termsOv").hidden = false; hideOsk();
});
$("termsClose").addEventListener("click", () => ($("termsOv").hidden = true));
// Privatlivssiden (hvad vi gemmer om gæsten, og hvor længe) i et vindue på skærmen.
$("privBtn").addEventListener("click", (e) => {
  e.stopPropagation();
  $("privFrame").src = "/privatliv/" + encodeURIComponent(TOKEN) + "?lang=" + (lang === "en" ? "en" : "da");
  $("privOv").hidden = false; hideOsk();
});
$("privClose").addEventListener("click", () => { $("privOv").hidden = true; $("privFrame").src = "about:blank"; });
$("termsAccept").addEventListener("click", () => { $("termsOv").hidden = true; termsOk(true); validate(); });

function prepName() {
  renderChosen(); renderExtras(); renderTerms();
  $("flPhone").hidden = !CFG.ask_phone;
  $("flCompany").hidden = !CFG.ask_company;
  $("nameOpt").hidden = CFG.name_required;
  $("phoneOpt").hidden = CFG.phone_required;
  if (visit.prefill) {
    const pf = visit.prefill; visit.prefill = null;
    $("fName").value = pf.guest_name || ""; $("fPhone").value = pf.guest_phone || ""; $("fCompany").value = pf.guest_company || "";
  } else if (!visit.name) { $("fName").value = ""; $("fPhone").value = ""; $("fCompany").value = ""; }
  validate(); updateBadge();
}
function digits(s) { return (s || "").replace(/\D/g, ""); }
function validate() {
  const okName = !CFG.name_required || $("fName").value.trim().length >= 2;
  const okPhone = !CFG.ask_phone || !CFG.phone_required || digits($("fPhone").value).length >= 8;
  const okTerms = !CFG.terms_enabled || $("termsOk").checked;
  $("checkinBtn").disabled = !(okName && okPhone && okTerms);
}
["fName", "fPhone", "fCompany"].forEach((id) => $(id).addEventListener("input", () => { validate(); updateBadge(); }));

let busy = false;
$("nameForm").addEventListener("submit", async (e) => {
  e.preventDefault(); if ($("checkinBtn").disabled || busy) return;
  busy = true; $("checkinBtn").disabled = true;
  const body = { host_id: visit.host ? visit.host.id : null, guest_name: $("fName").value.trim(),
    guest_phone: CFG.ask_phone ? $("fPhone").value.trim() : "", guest_company: CFG.ask_company ? $("fCompany").value.trim() : "", preview: PREVIEW,
    extra_guests: CFG.group_checkin ? extras.map((x) => x.trim()).filter(Boolean) : [], accept_terms: !!(CFG.terms_enabled && $("termsOk").checked),
    invitation_code: visit.invite || "", firm_id: FIRM ? FIRM.id : null };
  try {
    const r = await fetch(API + "/checkin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { toast(data.detail && typeof data.detail === "string" ? data.detail : t("errNet"), true); if (r.status === 404) loadConfig(); return; }
    visit.name = data.guest_name; visit.company = body.guest_company; visit.no = data.badge_no; visit.in = data.time; visit.id = data.visit_id;
    const guests = data.guests || [{ name: visit.name, badge_no: visit.no }];
    const names = guests.map((x) => first(x.name)).filter(Boolean);
    $("doneTitle").textContent = names.length > 1 ? t("guestsHi").replace("{n}", names.slice(0, -1).join(", ") + " " + t("and") + " " + names[names.length - 1]) : t("hi") + (names[0] ? ", " + names[0] : "");
    $("doneSub").textContent = visit.host ? t("notified").replace("{h}", first(visit.host.name)) : t("notifiedRec");
    $("printNote").hidden = !CFG.print_badge || MOBILE;
    $("wifiBox").hidden = !CFG.wifi_name; $("wifiName").textContent = CFG.wifi_name || ""; $("wifiPw").textContent = CFG.wifi_password || "–";
    const badges = guests.map((x) => ({ name: x.name, company: visit.company, host: visit.host ? visit.host.name : "", time: visit.in, no: x.badge_no }));
    $("inlineBadge").innerHTML = badgeHTML(badges[0], false);
    // Med værtens svar slået til står kvitteringen længere, så gæsten kan nå at se svaret.
    const waitReply = CFG.host_reply && visit.host && !PREVIEW;
    const ms = waitReply ? 45000 : 10000;
    $("doneTimer").style.setProperty("--d", ms / 1000 + "s");
    show("done"); restartTimer("doneTimer");
    if (waitReply) startReplyPoll(); else $("replyLine").hidden = true;
    if (CFG.print_badge && !PREVIEW && !MOBILE) printBadge(badges);
    clearTimeout(homeT); homeT = setTimeout(() => { if (cur === "done") home(); }, ms);
  } catch (err) {
    toast(t("errNet"), true);
  } finally { busy = false; validate(); }
});

// ---------- værtens svar ----------
// Spørger serveren hvert 3. sekund i op til 45 sekunder. Svaret ligger i serverens hukommelse,
// så det vækker ikke databasen.
let replyT = null;
function stopReplyPoll() { clearInterval(replyT); replyT = null; }
function startReplyPoll() {
  stopReplyPoll();
  const line = $("replyLine"), h = first(visit.host.name), vid = visit.id, started = Date.now();
  line.hidden = false; line.className = "replyline wait"; line.textContent = t("replyWait").replace("{h}", h);
  replyT = setInterval(async () => {
    if (cur !== "done" || Date.now() - started > 45000) return stopReplyPoll();
    try {
      const r = await fetch(API + "/reply/" + vid, { cache: "no-store" });
      const d = r.ok ? await r.json() : {};
      if (d.answer) {
        stopReplyPoll();
        line.className = "replyline got"; line.textContent = t("reply_" + d.answer).replace("{h}", h);
        clearTimeout(homeT); homeT = setTimeout(() => { if (cur === "done") home(); }, 15000);
      }
    } catch (e) {}
  }, 3000);
}

// ---------- pakke/levering ----------
let pkgTo = null;
function renderPkg() {
  if (CFG.house && !pkgFirm) {  // husets skærm: først firma, eller husets godsmodtagelse
    $("pkgHosts").innerHTML = CFG.firms.map((f) => '<button class="host firm" type="button" data-pfirm="' + f.id + '"><span class="pic">' + firmLogo(f) + '</span><span class="tx"><b>' + esc(f.name) + "</b></span></button>").join("") +
      '<button class="host any" type="button" data-pkg="any"><span class="pic">' + BELL + '</span><span class="tx"><b>' + t("pkgAny") + "</b><span>" + t("houseReception") + "</span></span></button>";
    $("pkgHosts").style.setProperty("--cols", 3);
    return;
  }
  const list = pkgFirm ? pkgFirm.hosts : CFG.hosts;
  $("pkgHosts").innerHTML = list.map((h) => '<button class="host" type="button" data-pkg="' + h.id + '"><span class="pic">' + pic(h) + '</span><span class="tx"><b>' + esc(h.name) + "</b><span>" + esc(h.title || "") + "</span></span></button>").join("") +
    '<button class="host any" type="button" data-pkg="any"><span class="pic">' + BELL + '</span><span class="tx"><b>' + (pkgFirm ? t("firmReception") : t("pkgAny")) + "</b><span>" + t("pkgAnySub") + "</span></span></button>";
  $("pkgHosts").style.setProperty("--cols", list.length + 1 <= 6 ? 3 : 4);
}
function renderPkgChosen() {
  const h = pkgTo;
  $("pkgChosen").innerHTML = '<span class="pic">' + (h ? (h.photo_url ? '<img src="' + esc(h.photo_url) + '" alt="">' : esc(initials(h.name))) : BELL) +
    "</span><div><small>" + t("pkgTo") + "</small><b>" + esc(h ? h.name : pkgFirm ? pkgFirm.name : t("pkgAny")) + "</b>" + (h && pkgFirm ? '<span class="firmname">' + esc(pkgFirm.name) + "</span>" : "") + "</div>";
}
$("pkgHosts").addEventListener("click", (e) => {
  const fb = e.target.closest("[data-pfirm]");
  if (fb) { pkgFirm = firmById(+fb.dataset.pfirm); renderPkg(); return; }
  const b = e.target.closest("[data-pkg]"); if (!b) return;
  pkgTo = b.dataset.pkg === "any" ? null : (pkgFirm ? pkgFirm.hosts : CFG.hosts).find((h) => String(h.id) === b.dataset.pkg);
  show("pkg2");
});
$("pkgForm").addEventListener("submit", async (e) => {
  e.preventDefault(); if (busy) return; busy = true; $("pkgSend").disabled = true;
  try {
    const r = await fetch(API + "/delivery", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host_id: pkgTo ? pkgTo.id : null, firm_id: pkgFirm ? pkgFirm.id : null, courier_company: $("pCompany").value.trim(), courier_name: $("pName").value.trim(), preview: PREVIEW }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast(typeof d.detail === "string" ? d.detail : t("errNet"), true); return; }
    $("pkgDoneSub").textContent = t("pkgDoneSub").replace("{h}", pkgTo ? first(pkgTo.name) : pkgFirm ? pkgFirm.name : t("pkgAny"));
    $("pkgNote").textContent = CFG.delivery_note || ""; $("pkgNote").hidden = !CFG.delivery_note;
    show("pkgdone"); restartTimer("pkgTimer");
    clearTimeout(homeT); homeT = setTimeout(() => { if (cur === "pkgdone") home(); }, 8000);
  } catch (err) { toast(t("errNet"), true); } finally { busy = false; $("pkgSend").disabled = false; }
});

// ---------- kode fra en invitation ----------
let codeVal = "", codeBusy = false;
function renderCode() {
  $("codeBoxes").innerHTML = [0, 1, 2, 3, 4, 5].map((i) => '<span class="' + (i < codeVal.length ? "on" : i === codeVal.length ? "cur" : "") + '">' + (codeVal[i] || "") + "</span>").join("");
  $("codePad").innerHTML = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "⌫"].map((k) =>
    '<button type="button" data-ck="' + k + '"' + (k === "clear" ? ' class="fn"' : k === "⌫" ? ' class="fn" aria-label="Slet"' : "") + ">" + (k === "clear" ? t("clear") : k) + "</button>").join("");
}
async function submitCode(code) {
  if (codeBusy) return; codeBusy = true; $("codeErr").hidden = true;
  try {
    const r = await fetch(API + "/code", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      $("codeErr").textContent = r.status === 429 && typeof d.detail === "string" ? d.detail : t("codeBad"); $("codeErr").hidden = false;
      $("codeBoxes").classList.remove("shake"); void $("codeBoxes").offsetWidth; $("codeBoxes").classList.add("shake");
      codeVal = ""; renderCode(); return;
    }
    if (d.firm_id) FIRM = firmById(d.firm_id);
    const host = d.host_id ? curHosts().find((h) => h.id === d.host_id) || null : null;
    visit = { host, in: hhmm(new Date()), invite: d.code, prefill: d };
    stopScan(); show("name");
  } catch (e) { toast(t("errNet"), true); } finally { codeBusy = false; }
}
$("codePad").addEventListener("click", (e) => {
  const b = e.target.closest("[data-ck]"); if (!b) return;
  const k = b.dataset.ck;
  if (k === "⌫") codeVal = codeVal.slice(0, -1); else if (k === "clear") codeVal = ""; else if (codeVal.length < 6) codeVal += k;
  renderCode();
  if (codeVal.length === 6) submitCode(codeVal);
});
// Kamera: kun hvor browseren har en indbygget QR-læser (BarcodeDetector, fx Chrome på Android og ChromeOS).
let scanStream = null, scanT = null;
const canScan = () => "BarcodeDetector" in window && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
function stopScan() {
  clearInterval(scanT); scanT = null;
  if (scanStream) { scanStream.getTracks().forEach((tr) => tr.stop()); scanStream = null; }
  $("scanBox").hidden = true; $("scanBtn").querySelector("span").textContent = t("scan");
}
$("scanBtn").addEventListener("click", async () => {
  if (scanStream) return stopScan();
  try {
    scanStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: MOBILE ? "environment" : "user" } });
    const v = $("scanVideo"); v.srcObject = scanStream; await v.play();
    $("scanBox").hidden = false; $("scanBtn").querySelector("span").textContent = t("scanStop");
    const det = new window.BarcodeDetector({ formats: ["qr_code"] });
    scanT = setInterval(async () => {
      try {
        const found = await det.detect(v);
        const digits = found.length ? found[0].rawValue.replace(/\D/g, "") : "";
        if (digits.length === 6) { codeVal = digits; renderCode(); stopScan(); submitCode(digits); }
      } catch (e) {}
    }, 400);
  } catch (e) { stopScan(); toast(t("codeLead"), true); }
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
function printBadge(list) {
  $("pageSize").textContent = "@media print{@page{size:" + (SIZES[CFG.badge_size] || "auto") + ";margin:0}#printArea .badge{break-after:page}}";
  $("printArea").innerHTML = [].concat(list).map((g) => badgeHTML(g, false)).join("");
  setTimeout(() => { try { window.print(); } catch (e) {} }, 500);
}

// ---------- on-screen keyboard ----------
const ROWS = [["1","2","3","4","5","6","7","8","9","0"],["q","w","e","r","t","y","u","i","o","p","å"],["a","s","d","f","g","h","j","k","l","æ","ø"],["⇧","z","x","c","v","b","n","m","-","⌫"],["@",".","space","OK"]];
const NUM = [["1","2","3"],["4","5","6"],["7","8","9"],["+","0","⌫"],["OK"]];
let shift = true, activeIn = null;
const useOsk = () => !MOBILE && (!matchMedia("(hover: hover) and (pointer: fine)").matches || PREVIEW || new URLSearchParams(location.search).has("osk"));
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
  if (CFG && cur === "closed" && isOpen()) { home(); return; }
  if (CFG && ["start", "lang"].includes(cur) && !isOpen()) { home(); return; }
  const homeScreen = isOpen() ? HOME() : "closed";
  const atHome = cur === homeScreen && lang === (LANGS().includes(CFG && CFG.lang_default) ? CFG.lang_default : LANGS()[0]);
  if (CFG && !["loading", "error"].includes(cur) && !atHome && Date.now() - lastAct > (CFG.idle_seconds || 60) * 1000) home();
}, 1000);
setInterval(() => { if (["start", "lang", "error", "closed"].includes(cur)) loadConfig(); }, 60000);
window.addEventListener("message", (e) => { if (e.origin === location.origin && e.data === "reload-config") { cfgSig = ""; loadConfig(); } });

let toastT;
function toast(m, err) { const x = $("toast"); x.textContent = m; x.classList.toggle("err", !!err); x.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (x.hidden = true), 3200); }

$("previewTag").hidden = !PREVIEW;
applyLang();
tick();
loadConfig();
try { navigator.wakeLock && navigator.wakeLock.request("screen").catch(() => {}); } catch (e) {}
})();
