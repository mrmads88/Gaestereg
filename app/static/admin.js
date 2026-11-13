(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const initials = (n) => String(n || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";

let tenants = [], partners = [], T = null, P = null, STATUS = null, ME = null, tab = "people", lastField = null;
const can = (k) => !!(ME && ME.can[k]);
const today = () => new Date().toISOString().slice(0, 10);

// ---------- api ----------
async function api(method, url, body, isForm) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) opt.body = body;
    else { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  }
  const r = await fetch(url, opt);
  if (r.status === 401 && !url.endsWith("/login")) { showLogin(); throw new Error("Log ind"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = msg.map((d) => (d.msg || "").replace(/^Value error, /, "")).join(". ");
    throw new Error(msg || "Noget gik galt (" + r.status + ")");
  }
  return data;
}
let toastT;
function toast(m, err) { const x = $("toast"); x.textContent = m; x.classList.toggle("err", !!err); x.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (x.hidden = true), 3200); }
let savedT;
function saved() { const s = $("saved"); s.hidden = false; clearTimeout(savedT); savedT = setTimeout(() => (s.hidden = true), 1600); }

// ---------- login ----------
let platformLogin = false;
function showCard(id) { ["loginForm", "forgotForm", "inviteForm"].forEach((x) => ($(x).hidden = x !== id)); }
function showLogin(msg) {
  $("appView").hidden = true; $("loginView").hidden = false; showCard("loginForm");
  $("loginErr").textContent = msg || ""; $("loginErr").hidden = !msg;
  (platformLogin ? $("pw") : $("loginEmail")).focus();
}
function setPlatformLogin(on) {
  platformLogin = on; $("emailFld").hidden = on;
  $("platformBtn").textContent = on ? "Log ind med e-mail" : "Leverandør-login";
  $("loginLead").textContent = on ? "Leverandør: log ind med din adgangskode." : "Log ind for at rette jeres skærm, personer og beskeder.";
}
$("platformBtn").addEventListener("click", () => { setPlatformLogin(!platformLogin); showLogin(); });
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault(); $("loginErr").hidden = true;
  const body = { email: platformLogin ? "" : $("loginEmail").value.trim(), password: $("pw").value };
  if (!platformLogin && !body.email) { $("loginErr").textContent = "Skriv din e-mail"; $("loginErr").hidden = false; return; }
  try { await api("POST", "/api/admin/login", body); $("pw").value = ""; boot(); }
  catch (err) { $("loginErr").textContent = err.message; $("loginErr").hidden = false; }
});
$("forgotBtn").addEventListener("click", () => { showCard("forgotForm"); $("forgotMsg").hidden = true; $("forgotEmail").value = $("loginEmail").value; $("forgotEmail").focus(); });
document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => { history.replaceState(null, "", "/admin"); showLogin(); }));
$("forgotForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { const r = await api("POST", "/api/admin/forgot", { email: $("forgotEmail").value.trim() }); $("forgotMsg").textContent = r.message; $("forgotMsg").hidden = false; }
  catch (err) { toast(err.message, true); }
});
$("logout").addEventListener("click", async () => { await api("POST", "/api/admin/logout").catch(() => {}); location.hash = ""; showLogin(); });

// invitation / ny adgangskode: /admin#invite=<token>
let inviteToken = null;
async function showInvite(token) {
  inviteToken = token;
  $("appView").hidden = true; $("loginView").hidden = false; showCard("inviteForm"); $("inviteErr").hidden = true;
  try {
    const info = await api("GET", "/api/admin/invite/" + encodeURIComponent(token));
    $("inviteTitle").textContent = info.new ? "Velkommen" + (info.name ? ", " + info.name.split(" ")[0] : "") : "Ny adgangskode";
    $("inviteLead").textContent = (info.new ? "Vælg en adgangskode til " : "Vælg en ny adgangskode til ") + info.email + ". Fremover logger du ind med din e-mail og den.";
    $("loginEmail").value = info.email; $("invPw").focus();
  } catch (err) { $("inviteTitle").textContent = "Linket virker ikke"; $("inviteLead").textContent = err.message; $("inviteForm").querySelectorAll("label,button[type=submit]").forEach((x) => (x.hidden = true)); }
}
$("inviteForm").addEventListener("submit", async (e) => {
  e.preventDefault(); $("inviteErr").hidden = true;
  if ($("invPw").value !== $("invPw2").value) { $("inviteErr").textContent = "De to adgangskoder er ikke ens"; $("inviteErr").hidden = false; return; }
  try {
    await api("POST", "/api/admin/invite/accept", { token: inviteToken, password: $("invPw").value });
    $("invPw").value = $("invPw2").value = ""; history.replaceState(null, "", "/admin"); boot();
  } catch (err) { $("inviteErr").textContent = err.message; $("inviteErr").hidden = false; }
});

async function boot() {
  const m = location.hash.match(/^#invite=(.+)$/);
  if (m) return showInvite(decodeURIComponent(m[1]));
  try { [STATUS, ME] = await Promise.all([api("GET", "/api/admin/status"), api("GET", "/api/admin/me")]); }
  catch (e) { if (!/Log ind/.test(e.message)) showLogin(e.message); return; }
  $("loginView").hidden = true; $("appView").hidden = false;
  setupRole();
  const env = STATUS.env;
  $("envPill").textContent = env === "prod" ? "Produktion" : env === "dev" ? "Dev" : "Lokal";
  $("envPill").className = "envpill " + env;
  const warn = [];
  if (STATUS.notify_mode !== "live") warn.push("Testtilstand: SMS og e-mails bliver logget under Besøg, men ikke sendt.");
  if (STATUS.default_password && ME.role === "platform") warn.push("Standard-adgangskoden bruges. Sæt ADMIN_PASSWORD.");
  $("banner").textContent = warn.join(" "); $("banner").hidden = !warn.length;
  await Promise.all([loadTenants(), loadPartners()]);
  const h = location.hash.match(/^#([tp])(\d+)$/);
  if (h && h[1] === "p") return selectPartner(+h[2]);
  if (h && h[1] === "t") return selectTenant(+h[2]);
  const last = recent()[0];
  if (last && last[0] === "p" && partners.some((x) => x.id === last[1])) return selectPartner(last[1]);
  if (last && last[0] === "t" && tenants.some((x) => x.id === last[1])) return selectTenant(last[1]);
  if (ME.role === "partner" && ME.partner) return selectPartner(ME.partner.id);
  if (tenants[0]) selectTenant(tenants[0].id);
}

// Tilbage/frem i browseren og indsatte links (#t12 / #p3) skifter kunde uden at genindlæse siden.
window.addEventListener("hashchange", () => {
  if ($("appView").hidden) return;
  const h = location.hash.match(/^#([tp])(\d+)$/); if (!h) return;
  const id = +h[2];
  if (h[1] === "t" && !(T && T.id === id && !P)) selectTenant(id);
  if (h[1] === "p" && !(P && P.id === id)) selectPartner(id);
});

// Hvad man ser, afhænger af rollen.
function setupRole() {
  const r = ME.role;
  $("who").textContent = r === "platform" ? "Leverandør" : (ME.name || ME.email) + (ME.partner ? " · " + ME.partner.name : "");
  document.querySelector(".cols").classList.toggle("solo", r === "tenant");
  $("partnerSec").hidden = r === "tenant";
  $("newPartner").hidden = !can("partners");
  $("partnerLbl").textContent = r === "platform" ? "Partnere" : "Partner";
  $("tenantLbl").textContent = r === "platform" ? "Kunder" : "Firmaer";
  $("newTenant").hidden = !can("create_tenant");
  $("newTenant").textContent = r === "platform" ? "+ Ny kunde" : "+ Nyt firma";
  $("newName").placeholder = r === "platform" ? "Kundens navn, fx Junckers" : "Firmaets navn";
  $("subTab").hidden = !can("subscription");
  $("activeFld").hidden = !can("toggle_active");
  $("delRow").hidden = !can("delete_tenant");
  $("pSettings").hidden = $("pDanger").hidden = !can("partners");
  $("switchBtn").hidden = r === "tenant";
  $("swKbd").textContent = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘K" : "Ctrl K";
}

// ---------- tenant list ----------
async function loadTenants() { tenants = await api("GET", "/api/admin/tenants"); renderList(); }
function tenantTags(t) {
  let out = "";
  if (!t.active) out += '<span class="tag off">slået fra</span>';
  else if (t.screen && t.screen.seen_at && !t.screen.online) out += '<span class="tag offline">skærm offline</span>';
  if (can("subscription")) {
    if (t.self_service) out += '<span class="tag ss">selvbetjening</span>';
    const until = t.subscription && t.subscription.sub_paid_until;
    if (until && until < today()) out += '<span class="tag exp">udløbet</span>';
  }
  return out;
}
function renderList() {
  const q = ($("tFilter").value || "").trim().toLowerCase();
  $("tFilter").hidden = tenants.length < 8;
  const shown = tenants.filter((t) => !q || t.name.toLowerCase().includes(q) || (t.partner_name || "").toLowerCase().includes(q));
  $("tList").innerHTML = shown.map((t) =>
    '<button class="titem" type="button" data-id="' + t.id + '" aria-current="' + (!!T && T.id === t.id && !P) + '"><span class="tl">' +
    (t.logo_url ? '<img src="' + esc(t.logo_url) + '" alt="">' : '<i style="background:' + esc(t.color) + '"></i>') +
    '</span><span class="grow"><b>' + esc(t.name) + "</b><small>" + t.host_count + " personer" +
    (ME.role === "platform" && t.partner_name ? " · " + esc(t.partner_name) : "") + tenantTags(t) + "</small></span></button>"
  ).join("") || '<p class="muted small">' + (q ? "Ingen match." : ME.role === "platform" ? "Ingen kunder endnu." : "Ingen firmaer endnu.") + "</p>";
}
$("tFilter").addEventListener("input", renderList);

// ---------- partners ----------
async function loadPartners() { partners = ME.role === "tenant" ? [] : await api("GET", "/api/admin/partners"); renderPartners(); }
function renderPartners() {
  $("pList").innerHTML = partners.map((x) =>
    '<button class="titem" type="button" data-pid="' + x.id + '" aria-current="' + (!!P && P.id === x.id) + '"><span class="tl p">' + esc(initials(x.name)) +
    '</span><span class="grow"><b>' + esc(x.name) + "</b><small>" + x.tenant_count + (x.tenant_count === 1 ? " firma" : " firmaer") + (x.active ? "" : '<span class="tag off">slået fra</span>') + "</small></span></button>"
  ).join("") || '<p class="muted small">Ingen partnere endnu. Fx et kontorhotel, der administrerer flere firmaer.</p>';
}
$("pList").addEventListener("click", (e) => { const b = e.target.closest("[data-pid]"); if (b) selectPartner(+b.dataset.pid); });
$("newPartner").addEventListener("click", () => { $("newPartnerForm").hidden = !$("newPartnerForm").hidden; if (!$("newPartnerForm").hidden) $("newPartnerName").focus(); });
$("newPartnerForm").addEventListener("submit", async (e) => {
  e.preventDefault(); const name = $("newPartnerName").value.trim(); if (!name) return;
  try { const x = await api("POST", "/api/admin/partners", { name }); $("newPartnerName").value = ""; $("newPartnerForm").hidden = true; await loadPartners(); selectPartner(x.id); toast(name + " er oprettet. Invitér en administrator."); }
  catch (err) { toast(err.message, true); }
});

function showView(v) { $("noTenant").hidden = true; $("editor").hidden = v !== "tenant"; $("partnerView").hidden = v !== "partner"; $("pv").hidden = v !== "tenant"; }
async function selectPartner(id) {
  P = partners.find((x) => x.id === id);
  if (!P) { await loadPartners(); P = partners.find((x) => x.id === id); }
  if (!P) return;
  T = null; location.hash = "p" + id; showView("partner"); remember("p", id); updateSwitcher();
  document.documentElement.style.setProperty("--accent", "#12352e");  // Nodd-grøn
  renderPartners(); renderList(); renderPartner();
}
async function renderPartner(keepImport) {
  $("pName").textContent = P.name; $("pvInitials").textContent = initials(P.name);
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);
  $("pSub").textContent = plural(P.tenant_count, "firma", "firmaer") + " · " + plural(P.user_count, "administrator", "administratorer");
  $("pNameIn").value = P.name; $("pActive").checked = P.active;
  document.querySelectorAll(".pn").forEach((x) => (x.textContent = P.name));
  const mine = tenants.filter((t) => t.partner_id === P.id);
  $("pCount").textContent = mine.length + " i alt";
  $("pTenants").innerHTML = mine.map((t) => '<button type="button" data-id="' + t.id + '"><span class="tl">' + (t.logo_url ? '<img src="' + esc(t.logo_url) + '" alt="">' : "") +
    '</span><span class="grow"><b>' + esc(t.name) + '</b><small class="muted">' + t.host_count + " personer" + tenantTags(t) + "</small></span></button>").join("") ||
    '<p class="muted">Ingen firmaer endnu. Opret dem ét ad gangen i listen til venstre, eller importér dem alle fra et Excel-ark ovenfor.</p>';
  $("pLink").hidden = true;
  if (!keepImport) renderImport($("pImport"), { partner_id: P.id, withFirm: true });
  renderUsers($("pUsers"), await api("GET", "/api/admin/partners/" + P.id + "/users").catch(() => []));
}
$("pTenants").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) selectTenant(+b.dataset.id); });
async function patchPartner(data) {
  try { const x = await api("PATCH", "/api/admin/partners/" + P.id, data); Object.assign(P, x); saved(); renderPartners(); renderPartner(); }
  catch (err) { toast(err.message, true); }
}
$("pNameIn").addEventListener("change", (e) => { const v = e.target.value.trim(); if (v) patchPartner({ name: v }); });
$("pActive").addEventListener("change", (e) => patchPartner({ active: e.target.checked }));
$("delPartner").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen for at slette " + P.name; setTimeout(() => { delete b.dataset.sure; b.textContent = "Slet partner"; }, 4000); return; }
  delete b.dataset.sure; b.textContent = "Slet partner";
  try { await api("DELETE", "/api/admin/partners/" + P.id); toast(P.name + " er slettet"); P = null; location.hash = ""; await loadPartners(); $("partnerView").hidden = true; $("noTenant").hidden = false; }
  catch (err) { toast(err.message, true); }
});
$("pInvite").addEventListener("submit", (e) => invite(e, "/api/admin/partners/" + P.id + "/users", $("pLink"), () => renderPartner()));
$("tList").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) selectTenant(+b.dataset.id); });
$("newTenant").addEventListener("click", () => { $("newForm").hidden = !$("newForm").hidden; if (!$("newForm").hidden) $("newName").focus(); });
$("newForm").addEventListener("submit", async (e) => {
  e.preventDefault(); const name = $("newName").value.trim(); if (!name) return;
  try {
    const t = await api("POST", "/api/admin/tenants", { name, partner_id: ME.role === "platform" && P ? P.id : null });
    if (P) await loadPartners();
    $("newName").value = ""; $("newForm").hidden = true;
    await loadTenants(); selectTenant(t.id); setTab("look"); toast(name + " er oprettet. Upload logoet og tilføj personer.");
  } catch (err) { toast(err.message, true); }
});

async function selectTenant(id) {
  try { T = await api("GET", "/api/admin/tenants/" + id); } catch (err) { toast(err.message, true); return; }
  P = null; location.hash = "t" + id; showView("tenant"); remember("t", id); updateSwitcher();
  if (tab === "sub" && !can("subscription")) tab = "people";
  renderList(); renderPartners(); renderAll(); setTab(tab); loadPreview(true);
}
function upsertList() { const i = tenants.findIndex((x) => x.id === T.id); if (i > -1) tenants[i] = Object.assign({}, T, { host_count: T.hosts.length }); renderList(); }

// ---------- render editor ----------
function renderAll() {
  renderHead(); bindFields(); renderHosts(); renderImages(); renderMsg(); renderSub();
  document.querySelectorAll(".tn").forEach((x) => (x.textContent = T.name));
  renderImport($("tImport"), { tenant_id: T.id, withFirm: false });
  $("tLink").hidden = true;
  if (tab === "log") loadLog();
  if (tab === "access") loadAccess();
}
function renderHead() {
  document.documentElement.style.setProperty("--accent", T.color);
  $("edName").textContent = T.name;
  $("edLogo").innerHTML = T.logo_url ? '<img src="' + esc(T.logo_url) + '" alt="">' : "<span>" + esc(initials(T.name)) + "</span>";
  const url = location.origin + T.kiosk_url;
  $("kioskUrl").textContent = url; $("openKiosk").href = T.kiosk_url;
  const sc = T.screen || {}, el = $("scrStatus");
  el.className = "scr " + (sc.online ? "on" : sc.seen_at ? "off" : "");
  el.innerHTML = "<i></i>" + (sc.online ? "Skærmen er online" : sc.seen_at ? "Skærm offline siden " + fmt(sc.seen_at) : "Skærm ikke set endnu");
  el.title = "Skærmen melder sig hvert minut, når den står på startskærmen.";
  updateSwitcher();
}
// ---------- sprog på skærmen ----------
const LANG_HINTS = {
  toggle: "Små flag i hjørnet af skærmen. Gæsten kan skifte sprog undervejs.",
  first: "Gæsten møder først store flag og vælger sprog, før de vælger person.",
  off: "Skærmen vises kun på standardsproget.",
};
const flagOf = (c) => { const L = window.NODD_LANG && window.NODD_LANG(c); return L ? '<span class="flag">' + L.flag() + "</span>" : ""; };
function renderLangs() {
  const on = T.languages || ["da"];
  $("langChecks").innerHTML = (window.NODD_LANGS || []).map((L) => '<label>' + '<input type="checkbox" value="' + L.code + '"' +
    (on.includes(L.code) ? " checked" : "") + (on.length === 1 && on.includes(L.code) ? " disabled" : "") + ">" + flagOf(L.code) + esc(L.name) + "</label>").join("");
  $("langDefault").innerHTML = on.map((c) => '<button type="button" data-v="' + c + '">' + flagOf(c) + esc((window.NODD_LANG(c) || {}).name || c) + "</button>").join("");
  const single = on.length < 2;
  $("langModeFld").hidden = single; $("langDefaultFld").hidden = single;
  $("langModeHint").textContent = LANG_HINTS[T.lang_mode] || "";
}
$("langChecks").addEventListener("change", () => {
  const langs = [...$("langChecks").querySelectorAll("input:checked")].map((x) => x.value);
  if (langs.length) patchTenant({ languages: langs });
});

// ---------- åbningstider ----------
const DAYS = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"];
const DEFAULT_HOURS = [["08:00", "16:00"], ["08:00", "16:00"], ["08:00", "16:00"], ["08:00", "16:00"], ["08:00", "15:00"], null, null];
function renderHours() {
  const h = T.opening_hours || [], on = h.length === 7;
  $("hoursOn").checked = on; $("hoursGrid").hidden = !on; $("closedFld").hidden = !on;
  if (!on) return;
  $("hoursGrid").innerHTML = DAYS.map((d, i) => { const v = h[i];
    return '<div class="day' + (v ? "" : " closed") + '" data-d="' + i + '"><b>' + d + '</b><label class="check"><input type="checkbox" data-open' + (v ? " checked" : "") + "> Åben</label>" +
      '<span class="t"><input type="time" data-from value="' + (v ? v[0] : "08:00") + '" aria-label="' + d + ' åbner"> til <input type="time" data-to value="' + (v ? v[1] : "16:00") + '" aria-label="' + d + ' lukker"></span></div>'; }).join("");
}
function readHours() {
  return [...$("hoursGrid").querySelectorAll(".day")].map((row) => row.querySelector("[data-open]").checked ? [row.querySelector("[data-from]").value, row.querySelector("[data-to]").value] : null);
}
$("hoursOn").addEventListener("change", (e) => patchTenant({ opening_hours: e.target.checked ? DEFAULT_HOURS : [] }));
$("hoursGrid").addEventListener("change", () => patchTenant({ opening_hours: readHours() }));

function bindFields() {
  renderLangs(); renderHours();
  document.querySelectorAll("#editor [data-f]").forEach((el) => {
    const v = T[el.dataset.f];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v == null ? "" : v;
  });
  document.querySelectorAll("#editor [data-seg]").forEach((s) => s.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(T[s.dataset.seg]) === b.dataset.v)));
  $("colorHex").value = T.color; $("dimVal").textContent = T.background_dim + " %";
  document.querySelector('[data-f="phone_required"]').closest(".switch").classList.toggle("dim", !T.ask_phone);
}
function renderImages() {
  $("logoPrev").innerHTML = T.logo_url ? '<img src="' + esc(T.logo_url) + '" alt="Logo">' : '<span class="muted">Intet logo</span>';
  $("bgPrev").style.backgroundImage = T.background_url ? 'url("' + T.background_url + '")' : "";
  $("bgPrev").innerHTML = T.background_url ? "" : '<span class="muted">Intet billede</span>';
}

// ---------- tenant field saving ----------
async function patchTenant(data) {
  try {
    T = Object.assign(T, await api("PATCH", "/api/admin/tenants/" + T.id, data));
    saved(); renderHead(); upsertList(); bindFields(); renderMsg(); loadPreview();
  } catch (err) { toast(err.message, true); bindFields(); }
}
function fieldValue(el) {
  if (el.type === "checkbox") return el.checked;
  if (el.type === "number" || el.type === "range") return parseInt(el.value, 10);
  return el.value;
}
document.querySelectorAll("#editor [data-f]").forEach((el) => {
  const ev = el.type === "checkbox" || el.type === "range" || el.type === "color" ? "change" : "change";
  el.addEventListener(ev, () => patchTenant({ [el.dataset.f]: fieldValue(el) }));
  if (el.tagName === "TEXTAREA" || el.type === "text" || !el.type || el.type === "email" || el.type === "tel") el.addEventListener("focus", () => (lastField = el));
});
document.querySelector('[data-f="background_dim"]').addEventListener("input", (e) => ($("dimVal").textContent = e.target.value + " %"));
$("colorPick").addEventListener("input", (e) => { $("colorHex").value = e.target.value; document.documentElement.style.setProperty("--accent", e.target.value); });
$("colorHex").addEventListener("change", (e) => {
  let v = e.target.value.trim(); if (!v.startsWith("#")) v = "#" + v;
  if (/^#[0-9a-fA-F]{6}$/.test(v)) patchTenant({ color: v.toLowerCase() }); else { toast("Skriv farven som #RRGGBB, fx #c8102e", true); e.target.value = T.color; }
});
document.querySelectorAll("#editor [data-seg]").forEach((s) => s.addEventListener("click", (e) => {
  const b = e.target.closest("[data-v]"); if (b) patchTenant({ [s.dataset.seg]: b.dataset.v });
}));
["sms_template", "email_template", "email_subject"].forEach((f) => document.querySelector('[data-f="' + f + '"]').addEventListener("input", renderSample));

// images
document.querySelectorAll("[data-upload]").forEach((inp) => inp.addEventListener("change", async () => {
  const f = inp.files && inp.files[0]; inp.value = ""; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try { T = Object.assign(T, await api("POST", "/api/admin/tenants/" + T.id + "/image/" + inp.dataset.upload, fd, true)); saved(); renderHead(); renderImages(); upsertList(); loadPreview(); }
  catch (err) { toast(err.message, true); }
}));
document.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
  try { T = Object.assign(T, await api("DELETE", "/api/admin/tenants/" + T.id + "/image/" + b.dataset.remove)); saved(); renderHead(); renderImages(); upsertList(); loadPreview(); }
  catch (err) { toast(err.message, true); }
}));

// danger zone
$("rotate").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen for at bekræfte"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Lav nyt link"; }, 4000); return; }
  delete b.dataset.sure; b.textContent = "Lav nyt link";
  try { T = Object.assign(T, await api("POST", "/api/admin/tenants/" + T.id + "/new-link")); renderHead(); loadPreview(true); toast("Nyt link lavet. Opdatér skærmen med det nye link."); } catch (err) { toast(err.message, true); }
});
$("delTenant").addEventListener("click", async (e) => {
  const b = e.currentTarget;
  if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen for at slette " + T.name; setTimeout(() => { delete b.dataset.sure; b.textContent = "Slet kunde"; }, 4000); return; }
  try {
    await api("DELETE", "/api/admin/tenants/" + T.id); toast(T.name + " er slettet");
    T = null; location.hash = ""; $("editor").hidden = true; $("pv").hidden = true; $("noTenant").hidden = false;
    delete b.dataset.sure; b.textContent = "Slet kunde"; await loadTenants();
  } catch (err) { toast(err.message, true); }
});
$("copyLink").addEventListener("click", () => {
  const url = $("kioskUrl").textContent;
  (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => toast("Link kopieret"), () => {
    const r = document.createRange(); r.selectNodeContents($("kioskUrl")); const s = getSelection(); s.removeAllRanges(); s.addRange(r); toast("Markeret. Kopiér med Ctrl+C");
  });
});

// ---------- tabs ----------
function setTab(name) {
  tab = name;
  document.querySelectorAll("#tabs [data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  document.querySelectorAll("#editor .tab").forEach((s) => (s.hidden = s.id !== "tab-" + name));
  if (name === "log") loadLog();
  if (name === "access") loadAccess();
}
$("tabs").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) setTab(b.dataset.tab); });

// ---------- hosts ----------
const I = {
  up: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg>',
  dn: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  x: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
};
function hostWarnings(h) {
  const w = [];
  if (h.notify_sms && !h.phone) w.push("SMS valgt, men mobil mangler");
  if (h.notify_email && !h.email) w.push("E-mail valgt, men adresse mangler");
  if (!((h.notify_sms && h.phone) || (h.notify_email && h.email))) w.push("Får ingen besked");
  return w;
}
function hostRow(h, i, n) {
  const warn = hostWarnings(h);
  return '<div class="host' + (h.active ? "" : " inactive") + '" data-hid="' + h.id + '">' +
    '<label class="photo" title="Skift billede">' + (h.photo_url ? '<img src="' + esc(h.photo_url) + '" alt="">' : esc(initials(h.name))) +
      '<span class="ov">' + (h.photo_url ? "Skift" : "Tilføj billede") + '</span><input type="file" accept="image/*" data-photo aria-label="Billede af ' + esc(h.name) + '"></label>' +
    '<div class="hfields">' +
      '<input data-h="name" value="' + esc(h.name) + '" aria-label="Navn" maxlength="120">' +
      '<input data-h="title" value="' + esc(h.title) + '" placeholder="Titel" aria-label="Titel" maxlength="120">' +
      '<input data-h="email" value="' + esc(h.email) + '" placeholder="E-mail" type="email" aria-label="E-mail" maxlength="200">' +
      '<input data-h="phone" value="' + esc(h.phone) + '" placeholder="Mobil" type="tel" aria-label="Mobil" maxlength="40">' +
      '<div class="hnote"><span class="lbl">Besked via</span>' +
        '<label class="check"><input type="checkbox" data-h="notify_sms"' + (h.notify_sms ? " checked" : "") + "> SMS</label>" +
        '<label class="check"><input type="checkbox" data-h="notify_email"' + (h.notify_email ? " checked" : "") + "> E-mail</label>" +
        '<label class="check"><input type="checkbox" data-h="active"' + (h.active ? " checked" : "") + "> Vises på skærmen</label>" +
        warn.map((w) => '<span class="warn">' + esc(w) + "</span>").join("") + "</div>" +
    "</div>" +
    '<div class="hact"><div class="iconrow">' +
      '<button class="ib" type="button" data-mv="-1" aria-label="Flyt op"' + (i === 0 ? " disabled" : "") + ">" + I.up + "</button>" +
      '<button class="ib" type="button" data-mv="1" aria-label="Flyt ned"' + (i === n - 1 ? " disabled" : "") + ">" + I.dn + "</button>" +
      '<button class="ib del" type="button" data-del aria-label="Slet ' + esc(h.name) + '">' + I.x + "</button></div>" +
      '<button class="btn ghost sm" type="button" data-test>Send test</button>' +
      (h.photo_url ? '<button class="btn ghost sm" type="button" data-nophoto>Fjern billede</button>' : "") +
    "</div></div>";
}
function renderHosts() {
  $("hostList").innerHTML = T.hosts.map((h, i) => hostRow(h, i, T.hosts.length)).join("") || '<div class="card"><p class="muted">Ingen personer endnu. Tilføj den første herunder.</p></div>';
}
const hostOf = (el) => { const r = el.closest("[data-hid]"); return r ? T.hosts.find((h) => h.id === +r.dataset.hid) : null; };
function replaceHost(h) { const i = T.hosts.findIndex((x) => x.id === h.id); if (i > -1) T.hosts[i] = h; }
$("hostList").addEventListener("change", async (e) => {
  const h = hostOf(e.target); if (!h) return;
  if (e.target.hasAttribute("data-photo")) {
    const f = e.target.files && e.target.files[0]; e.target.value = ""; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { replaceHost(await api("POST", "/api/admin/hosts/" + h.id + "/photo", fd, true)); saved(); renderHosts(); loadPreview(); } catch (err) { toast(err.message, true); }
    return;
  }
  const f = e.target.dataset.h; if (!f) return;
  const v = e.target.type === "checkbox" ? e.target.checked : e.target.value.trim();
  if (f === "name" && !v) { toast("Navnet må ikke være tomt", true); e.target.value = h.name; return; }
  try { replaceHost(await api("PATCH", "/api/admin/hosts/" + h.id, { [f]: v })); saved(); renderHosts(); loadPreview(); upsertList(); }
  catch (err) { toast(err.message, true); renderHosts(); }
});
$("hostList").addEventListener("click", async (e) => {
  const h = hostOf(e.target); if (!h) return; let b;
  if ((b = e.target.closest("[data-mv]"))) {
    const i = T.hosts.indexOf(h), j = i + +b.dataset.mv; if (j < 0 || j >= T.hosts.length) return;
    const ids = T.hosts.map((x) => x.id); ids.splice(j, 0, ids.splice(i, 1)[0]);
    try { T.hosts = await api("POST", "/api/admin/tenants/" + T.id + "/hosts/order", { ids }); saved(); renderHosts(); loadPreview(); } catch (err) { toast(err.message, true); }
  } else if ((b = e.target.closest("[data-del]"))) {
    if (!b.dataset.sure) { b.dataset.sure = "1"; b.style.background = "var(--bad)"; b.style.color = "#fff"; toast("Tryk på krydset igen for at slette " + h.name); setTimeout(() => { delete b.dataset.sure; b.style.background = ""; b.style.color = ""; }, 3500); return; }
    try { await api("DELETE", "/api/admin/hosts/" + h.id); T.hosts = T.hosts.filter((x) => x.id !== h.id); renderHosts(); upsertList(); loadPreview(); toast(h.name + " er slettet"); } catch (err) { toast(err.message, true); }
  } else if (e.target.closest("[data-nophoto]")) {
    try { replaceHost(await api("DELETE", "/api/admin/hosts/" + h.id + "/photo")); renderHosts(); loadPreview(); } catch (err) { toast(err.message, true); }
  } else if ((b = e.target.closest("[data-test]"))) {
    b.disabled = true;
    try {
      const res = await api("POST", "/api/admin/hosts/" + h.id + "/test");
      const txt = res.map((r) => (r.channel === "sms" ? "SMS" : "E-mail") + " til " + r.recipient + ": " + ({ sendt: "sendt", test: "logget (testtilstand)", fejl: "fejlede, " + r.error }[r.status] || r.status)).join(" · ");
      toast(txt, res.some((r) => r.status === "fejl"));
    } catch (err) { toast(err.message, true); }
    b.disabled = false;
  }
});
$("addHost").addEventListener("submit", async (e) => {
  e.preventDefault(); const f = e.target;
  const body = { name: f.name.value.trim(), title: f.title.value.trim(), email: f.email.value.trim(), phone: f.phone.value.trim(),
    notify_sms: f.notify_sms.checked, notify_email: f.notify_email.checked };
  if (!body.name) return;
  try { T.hosts.push(await api("POST", "/api/admin/tenants/" + T.id + "/hosts", body)); f.reset(); f.notify_sms.checked = f.notify_email.checked = true; renderHosts(); upsertList(); loadPreview(); f.name.focus(); toast(body.name + " er tilføjet"); }
  catch (err) { toast(err.message, true); }
});

// ---------- messages ----------
const FIELDS = [["vaert_fornavn", "værtens fornavn"], ["vaert", "værtens fulde navn"], ["gaest", "gæstens navn"], ["telefon", "gæstens mobil"], ["firma", "gæstens firma"], ["tid", "klokkeslæt"], ["kunde", "kundens navn"], ["svarlink", "link værten svarer på"]];
const SAMPLE = { vaert_fornavn: "Anne", vaert: "Anne Kjær", gaest: "Mads Hansen", telefon: "+45 20 30 40 50", firma: "Hansen ApS", tid: "10:42", kunde: "", svarlink: location.origin + "/r/…" };
function fill(tpl) { return String(tpl || "").replace(/\{(\w+)\}/g, (m, k) => (k in SAMPLE ? (k === "kunde" ? T.name : SAMPLE[k]) : m)); }
function renderSample() {
  const sms = document.querySelector('[data-f="sms_template"]').value;
  let text = fill(sms);
  if (T.host_reply && !sms.includes("{svarlink}")) text += "\nSvar: " + location.origin + "/r/…";
  $("sample").textContent = (document.querySelector('[data-f="sms_sender"]').value || "Reception") + ":\n" + text;
  const parts = text.length <= 160 ? 1 : Math.ceil(text.length / 153);
  $("smsCount").textContent = text.length + " tegn · " + parts + " SMS";
}
function renderMsg() {
  $("chips").innerHTML = FIELDS.map((f) => '<button type="button" data-ins="{' + f[0] + '}">{' + f[0] + "}<small>" + f[1] + "</small></button>").join("");
  if (STATUS) {
    const live = STATUS.notify_mode === "live";
    const st = (ok, label) => '<span class="st ' + (live ? (ok ? "ok" : "bad") : "warn") + '"><i></i>' + label + "</span>";
    $("msgStatus").innerHTML = (live ? "" : '<span class="st warn"><i></i>Testtilstand: intet sendes</span>') +
      st(STATUS.sms_configured, "SMS " + (STATUS.sms_configured ? "sat op" : "ikke sat op")) +
      st(STATUS.smtp_configured, "E-mail " + (STATUS.smtp_configured ? "sat op" : "ikke sat op"));
  }
  renderSample();
}
$("chips").addEventListener("click", (e) => {
  const b = e.target.closest("[data-ins]"); if (!b) return;
  const el = lastField && lastField.closest("#tab-msg") ? lastField : document.querySelector('[data-f="sms_template"]');
  const s = el.selectionStart ?? el.value.length, en = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0, s) + b.dataset.ins + el.value.slice(en);
  el.focus(); el.selectionStart = el.selectionEnd = s + b.dataset.ins.length;
  renderSample(); el.dispatchEvent(new Event("change"));
});

// ---------- log ----------
const fmt = (iso) => iso ? new Date(iso).toLocaleString("da-DK", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
async function loadLog() {
  if (!T) return;
  try {
    const [v, n] = await Promise.all([api("GET", "/api/admin/tenants/" + T.id + "/visits"), api("GET", "/api/admin/tenants/" + T.id + "/notifications")]);
    VISITS = v; $("delBar").hidden = true;
    $("visitRows").innerHTML = v.map((x) => '<tr data-vid="' + x.id + '"><td class=n>' + fmt(x.checked_in_at) + "</td><td>" + esc(x.guest_name || (x.kind === "delivery" ? "Bud" : "")) + (x.kind === "delivery" ? ' <span class="tag pkg">pakke</span>' : "") + (x.terms_accepted ? ' <span class="tag ss" title="Har accepteret husreglerne">regler ✓</span>' : "") + "</td><td class=n>" + esc(x.guest_phone) + "</td><td>" + esc(x.guest_company) + "</td><td>" + esc(x.host_name) + (x.host_reply ? '<div class="small muted">' + esc({ now: "Kommer nu", "5": "Om 5 min", "10": "Om 10 min", reception: "Receptionen tager den" }[x.host_reply] || "") + "</div>" : "") + "</td><td class=n>" + (x.checked_out_at ? fmt(x.checked_out_at).split(" ").pop() : "") +
      '</td><td><button class="ib del" type="button" data-delvisit aria-label="Slet besøget fra ' + esc(x.guest_name) + '">' + I.x + "</button></td></tr>").join("") || '<tr><td colspan="7" class="muted">Ingen besøg endnu.</td></tr>';
    $("noteRows").innerHTML = n.map((x) => "<tr><td class=n>" + fmt(x.created_at) + "</td><td>" + ({ sms: "SMS", email: "E-mail", teams: "Teams" }[x.channel] || x.channel) + "</td><td>" + esc(x.recipient) + '</td><td><span class="pill ' + esc(x.status) + '">' + esc(x.status) + "</span>" + (x.error ? '<div class="small" style="color:var(--bad)">' + esc(x.error) + "</div>" : "") + '</td><td><div class="body">' + esc(x.subject ? x.subject + "\n\n" + x.body : x.body) + "</div></td></tr>").join("") || '<tr><td colspan="5" class="muted">Ingen beskeder endnu.</td></tr>';
  } catch (err) { toast(err.message, true); }
}
$("refreshLog").addEventListener("click", loadLog);
let VISITS = [];
$("visitRows").addEventListener("click", (e) => {
  const b = e.target.closest("[data-delvisit]"); if (!b) return;
  const v = VISITS.find((x) => x.id === +b.closest("[data-vid]").dataset.vid); if (!v) return;
  const bar = $("delBar");
  bar.innerHTML = "<span class=grow>Slet besøget fra <b>" + esc(v.guest_name || "ukendt gæst") + "</b>" + (v.guest_phone ? " (" + esc(v.guest_phone) + ")" : "") + "? Det kan ikke fortrydes.</span>" +
    '<button class="btn bad sm" type="button" data-del-one>Kun dette besøg</button><button class="btn bad sm" type="button" data-del-all>Alle besøg fra gæsten</button><button class="btn ghost sm" type="button" data-del-no>Annullér</button>';
  bar.hidden = false; bar.dataset.vid = v.id; bar.scrollIntoView({ block: "nearest" });
});
$("delBar").addEventListener("click", async (e) => {
  const bar = $("delBar"); const all = !!e.target.closest("[data-del-all]");
  if (e.target.closest("[data-del-no]")) { bar.hidden = true; return; }
  if (!all && !e.target.closest("[data-del-one]")) return;
  try {
    const r = await api("DELETE", "/api/admin/tenants/" + T.id + "/visits/" + bar.dataset.vid + (all ? "?everything=true" : ""));
    toast(r.deleted === 1 ? "1 besøg er slettet" : r.deleted + " besøg er slettet"); loadLog();
  } catch (err) { toast(err.message, true); }
});

// ---------- kundeskifter (Ctrl/⌘ K) ----------
function recent() { try { return JSON.parse(localStorage.getItem("nodd-recent") || "[]"); } catch (e) { return []; } }
function remember(kind, id) {
  const r = recent().filter((x) => !(x[0] === kind && x[1] === id)); r.unshift([kind, id]);
  try { localStorage.setItem("nodd-recent", JSON.stringify(r.slice(0, 6))); } catch (e) {}
}
const logoBox = (t) => '<span class="sw-logo">' + (t.logo_url ? '<img src="' + esc(t.logo_url) + '" alt="">' : '<i style="background:' + esc(t.color) + '"></i>') + "</span>";
function updateSwitcher() {
  if (T) { $("swLogo").outerHTML = logoBox(T).replace('class="sw-logo"', 'class="sw-logo" id="swLogo"'); $("swName").textContent = T.name; }
  else if (P) { $("swLogo").outerHTML = '<span class="sw-logo" id="swLogo"><b style="font-size:.7rem">' + esc(initials(P.name)) + "</b></span>"; $("swName").textContent = P.name; }
}
let palSel = 0, palItems = [];
function palRender() {
  const q = $("palQ").value.trim().toLowerCase();
  const tItem = (t) => ({ kind: "t", id: t.id, html: logoBox(t) + "<span class=grow><b>" + esc(t.name) + "</b><small>" + t.host_count + " personer" + (t.partner_name ? " · " + esc(t.partner_name) : "") + tenantTags(t) + "</small></span>" });
  const pItem = (x) => ({ kind: "p", id: x.id, html: '<span class="tl p">' + esc(initials(x.name)) + "</span><span class=grow><b>" + esc(x.name) + "</b><small>Partner · " + x.tenant_count + (x.tenant_count === 1 ? " firma" : " firmaer") + "</small></span>" });
  const match = (s) => !q || s.toLowerCase().includes(q);
  const groups = [];
  if (!q) {
    const rec = recent().map(([k, id]) => k === "t" ? tenants.find((t) => t.id === id) && tItem(tenants.find((t) => t.id === id)) : partners.find((x) => x.id === id) && pItem(partners.find((x) => x.id === id))).filter(Boolean).slice(0, 5);
    if (rec.length) groups.push(["Senest åbnet", rec]);
  }
  const ps = partners.filter((x) => match(x.name)).map(pItem);
  if (ps.length) groups.push([ME.role === "platform" ? "Partnere" : "Partner", ps]);
  const ts = tenants.filter((t) => match(t.name) || match(t.partner_name || "")).map(tItem);
  if (ts.length) groups.push([ME.role === "platform" ? "Kunder" : "Firmaer", ts]);
  palItems = groups.flatMap((g) => g[1]);
  palSel = Math.min(palSel, Math.max(0, palItems.length - 1));
  let i = 0;
  $("palList").innerHTML = groups.map(([label, items]) => '<div class="grp">' + label + "</div>" + items.map((it) =>
    '<button class="pal-item" type="button" role="option" data-i="' + (i++) + '" aria-selected="' + (i - 1 === palSel) + '">' + it.html + "</button>").join("")).join("") ||
    '<p class="pal-empty">Ingen kunder matcher "' + esc(q) + '".</p>';
  const cur = $("palList").querySelector('[aria-selected="true"]'); if (cur) cur.scrollIntoView({ block: "nearest" });
}
function palOpen() { if (ME.role === "tenant") return; $("palette").hidden = false; $("palQ").value = ""; palSel = 0; palRender(); $("palQ").focus(); }
function palClose() { $("palette").hidden = true; }
function palGo(i) { const it = palItems[i]; if (!it) return; palClose(); it.kind === "t" ? selectTenant(it.id) : selectPartner(it.id); }
$("switchBtn").addEventListener("click", palOpen);
$("palQ").addEventListener("input", () => { palSel = 0; palRender(); });
$("palList").addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (b) palGo(+b.dataset.i); });
$("palette").addEventListener("click", (e) => { if (e.target === $("palette")) palClose(); });
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k" && !$("appView").hidden) { e.preventDefault(); $("palette").hidden ? palOpen() : palClose(); return; }
  if ($("palette").hidden) return;
  if (e.key === "Escape") palClose();
  else if (e.key === "ArrowDown") { e.preventDefault(); palSel = Math.min(palSel + 1, palItems.length - 1); palRender(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); palSel = Math.max(palSel - 1, 0); palRender(); }
  else if (e.key === "Enter") { e.preventDefault(); palGo(palSel); }
});

// ---------- users (adgang) ----------
const fmtDay = (iso) => iso ? new Date(iso).toLocaleDateString("da-DK", { day: "numeric", month: "short", year: "numeric" }) : "";
function renderUsers(box, users) {
  const myEmail = ME.email;
  box.innerHTML = users.map((u) => '<div class="urow" data-uid="' + u.id + '"><span class="av">' + esc(initials(u.name || u.email)) + '</span><span class="grow"><b>' +
    esc(u.name || u.email) + "</b><small>" + (u.name ? esc(u.email) + " · " : "") +
    (u.pending ? '<span class="pend">Har ikke valgt adgangskode endnu</span>' : u.last_login_at ? "Sidst logget ind " + fmtDay(u.last_login_at) : "Ikke logget ind endnu") + "</small></span>" +
    '<button class="btn ghost sm" type="button" data-link>' + (u.pending ? "Nyt invitationslink" : "Link til ny adgangskode") + "</button>" +
    (u.email === myEmail ? "" : '<button class="btn ghost sm" type="button" data-rm>Fjern</button>') + "</div>").join("") ||
    '<p class="muted small">Ingen administratorer endnu.</p>';
}
function showLink(box, res, what) {
  const sent = res.emailed ? "Linket er sendt til " + res.user.email + "." : "Send linket til " + res.user.email + " (fx på mail eller Teams).";
  box.innerHTML = "<b>" + esc(what) + "</b><span class=small>" + esc(sent) + " Det virker i 7 dage og kan kun bruges én gang.</span><code>" + esc(res.invite_url) + '</code><div><button class="btn ghost sm" type="button">Kopiér link</button></div>';
  box.hidden = false;
  box.querySelector("button").addEventListener("click", () => (navigator.clipboard ? navigator.clipboard.writeText(res.invite_url) : Promise.reject()).then(() => toast("Link kopieret"), () => toast("Markér linket og kopiér med Ctrl+C", true)));
}
async function invite(e, url, linkBox, after) {
  e.preventDefault(); const f = e.target;
  try {
    const res = await api("POST", url, { email: f.email.value.trim(), name: f.name.value.trim() });
    f.reset(); showLink(linkBox, res, (res.user.name || res.user.email) + " er inviteret"); await after(); linkBox.hidden = false;
  } catch (err) { toast(err.message, true); }
}
async function userAction(e, linkBox, after) {
  const row = e.target.closest("[data-uid]"); if (!row) return; const uid = row.dataset.uid; let b;
  if ((b = e.target.closest("[data-link]"))) {
    try { const res = await api("POST", "/api/admin/users/" + uid + "/link"); showLink(linkBox, res, "Nyt link til " + (res.user.name || res.user.email)); toast("Det gamle link virker ikke længere"); }
    catch (err) { toast(err.message, true); }
  } else if ((b = e.target.closest("[data-rm]"))) {
    if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Fjern"; }, 3500); return; }
    try { await api("DELETE", "/api/admin/users/" + uid); toast("Fjernet"); await after(); } catch (err) { toast(err.message, true); }
  }
}
$("pUsers").addEventListener("click", (e) => userAction(e, $("pLink"), () => renderPartner().then(() => loadPartners())));
$("tUsers").addEventListener("click", (e) => userAction(e, $("tLink"), loadAccess));
$("tInvite").addEventListener("submit", (e) => invite(e, "/api/admin/tenants/" + T.id + "/users", $("tLink"), loadAccess));
async function loadAccess() {
  if (!T) return;
  const w = $("ssWarn");
  w.hidden = !!T.self_service;
  w.textContent = ME.role === "platform" ? "Selvbetjening er ikke slået til for " + T.name + ". Administratorerne kan først logge ind, når du slår det til under Abonnement."
    : "Selvbetjening er ikke slået til for " + T.name + ". Administratorerne kan først logge ind, når den er aktiveret. Kontakt din leverandør.";
  try { renderUsers($("tUsers"), await api("GET", "/api/admin/tenants/" + T.id + "/users")); } catch (err) { toast(err.message, true); }
}

// ---------- abonnement (kun platform) ----------
function renderSub() {
  if (!can("subscription") || !T.subscription) return;
  const S = T.subscription;
  $("subPartner").innerHTML = '<option value="">Ingen (direkte kunde)</option>' + partners.map((x) => '<option value="' + x.id + '">' + esc(x.name) + "</option>").join("");
  document.querySelectorAll("[data-s]").forEach((el) => {
    const v = S[el.dataset.s];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v == null ? "" : v;
  });
  const year = (S.sub_yearly_price || 0) + (S.self_service ? (S.self_service_monthly_price || 0) * 12 : 0);
  const until = S.sub_paid_until;
  $("subSummary").textContent = "I alt " + year.toLocaleString("da-DK") + " kr. pr. år" +
    (until ? (until < today() ? ". Udløb " : ". Betalt til ") + new Date(until).toLocaleDateString("da-DK", { day: "numeric", month: "long", year: "numeric" }) + "." : ". Ingen betalingsdato sat.");
}
document.querySelectorAll("[data-s]").forEach((el) => el.addEventListener("change", async () => {
  const k = el.dataset.s;
  let v = el.type === "checkbox" ? el.checked : el.value;
  if (el.type === "number") v = v === "" ? 0 : parseInt(v, 10);
  if (k === "partner_id") v = v === "" ? null : +v;
  if (k === "sub_paid_until" && v === "") v = null;
  try {
    T = Object.assign(T, await api("PATCH", "/api/admin/tenants/" + T.id + "/subscription", { [k]: v }));
    saved(); renderSub(); upsertList(); if (k === "partner_id") { await loadTenants(); await loadPartners(); }
    if (k === "self_service" && tab === "access") loadAccess();
  } catch (err) { toast(err.message, true); renderSub(); }
}));

// ---------- import ----------
function renderImport(box, opt) {
  const tpl = "/api/admin/import/template?firma=" + (opt.withFirm ? "1" : "0");
  box.innerHTML = '<div class="imp"><ol>' +
    '<li>Hent skabelonen og udfyld én række pr. person' + (opt.withFirm ? ", med firmaets navn i første kolonne. Nye firmaer oprettes automatisk." : ".") + "</li>" +
    "<li>Billeder: sæt dem ind i arket ud for personen, eller læg arket og billederne i én ZIP-fil.</li>" +
    "<li>Upload filen. Du ser først en forhåndsvisning. Intet gemmes, før du trykker Importér.</li></ol>" +
    '<div class="row"><a class="btn ghost sm" href="' + tpl + '" download>Hent skabelon (Excel)</a>' +
    '<label class="btn pri sm file">Vælg fil<input type="file" accept=".xlsx,.csv,.zip" aria-label="Vælg Excel-, CSV- eller ZIP-fil"></label></div>' +
    '<div class="impres"></div></div>';
  let file = null;
  const res = box.querySelector(".impres");
  const send = async (dry) => {
    const fd = new FormData(); fd.append("file", file); fd.append("dry_run", dry ? "true" : "false");
    if (opt.tenant_id) fd.append("tenant_id", opt.tenant_id);
    if (opt.partner_id && ME.role === "platform") fd.append("partner_id", opt.partner_id);
    return api("POST", "/api/admin/import", fd, true);
  };
  box.querySelector("input[type=file]").addEventListener("change", async (e) => {
    file = e.target.files && e.target.files[0]; e.target.value = ""; if (!file) return;
    res.innerHTML = '<p class="muted">Læser ' + esc(file.name) + " …</p>";
    try { showResult(await send(true)); } catch (err) { res.innerHTML = '<p class="err">' + esc(err.message) + "</p>"; }
  });
  function showResult(r) {
    const n = r.people_new + r.people_updated;
    const sum = [];
    if (opt.withFirm) sum.push("<span><b>" + r.firms_new.length + "</b>nye firmaer</span>");
    sum.push("<span><b>" + r.people_new + "</b>nye personer</span>", "<span><b>" + r.people_updated + "</b>opdateres</span>", "<span><b>" + r.photos + "</b>billeder</span>");
    if (r.errors.length) sum.push('<span style="color:var(--bad)"><b>' + r.errors.length + "</b>" + (r.errors.length === 1 ? "række springes" : "rækker springes") + " over</span>");
    res.innerHTML = (r.dry_run ? "<h3>Forhåndsvisning af " + esc(file.name) + "</h3>" : "<h3>Importeret</h3>") +
      '<div class="impsum">' + sum.join("") + "</div>" +
      (r.firms_new.length ? '<p class="small">Nye firmaer: ' + r.firms_new.map(esc).join(", ") + "</p>" : "") +
      (r.errors.length ? '<ul class="implist err">' + r.errors.map((x) => "<li>Række " + x.row + ": " + esc(x.message) + "</li>").join("") + "</ul>" : "") +
      (r.warnings.length ? '<ul class="implist warn">' + r.warnings.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" : "") +
      (r.rows.length ? '<div class="tablewrap"><table><thead><tr><th>Række</th>' + (opt.withFirm ? "<th>Firma</th>" : "") + "<th>Navn</th><th></th><th>Billede</th></tr></thead><tbody>" +
        r.rows.slice(0, 200).map((x) => "<tr><td class=n>" + x.row + "</td>" + (opt.withFirm ? "<td>" + esc(x.firm) + "</td>" : "") + "<td>" + esc(x.name) + '</td><td class="act-' + x.action + '">' + (x.action === "ny" ? "Ny" : "Opdateres") + "</td><td>" + (x.photo ? "Ja" : "") + "</td></tr>").join("") +
        "</tbody></table></div>" : "") +
      (r.dry_run && n ? '<div class="row"><button class="btn pri" type="button" data-go>Importér ' + n + " personer</button><button class=\"btn ghost\" type=button data-cancel>Annullér</button></div>" : "");
    const go = res.querySelector("[data-go]");
    if (go) go.addEventListener("click", async () => {
      go.disabled = true; go.textContent = "Importerer …";
      try {
        const done = await send(false); showResult(done);
        toast(done.people_new + " personer oprettet og " + done.people_updated + " opdateret");
        await loadTenants(); if (P) { await loadPartners(); P = partners.find((x) => x.id === P.id) || P; renderPartners(); renderPartner(true); }
        if (T && opt.tenant_id) { T = await api("GET", "/api/admin/tenants/" + T.id); renderHosts(); upsertList(); loadPreview(); }
      } catch (err) { toast(err.message, true); go.disabled = false; go.textContent = "Prøv igen"; }
    });
    const cancel = res.querySelector("[data-cancel]");
    if (cancel) cancel.addEventListener("click", () => { res.innerHTML = ""; file = null; });
  }
}

// ---------- preview ----------
let pvToken = null, pvT;
function fitPreview() { const f = $("pvFrame"); $("pvIframe").style.transform = "scale(" + f.clientWidth / 1280 + ")"; }
function loadPreview(hard) {
  if (!T) return;
  clearTimeout(pvT);
  pvT = setTimeout(() => {
    const ifr = $("pvIframe");
    if (hard || pvToken !== T.kiosk_token) { pvToken = T.kiosk_token; ifr.src = T.kiosk_url + "?preview=1"; }
    else { try { ifr.contentWindow.postMessage("reload-config", location.origin); } catch (e) { ifr.src = ifr.src; } }
    fitPreview();
  }, hard ? 0 : 250);
}
$("pvReload").addEventListener("click", () => loadPreview(true));
window.addEventListener("resize", fitPreview);
new ResizeObserver(fitPreview).observe($("pvFrame"));

boot();
})();
