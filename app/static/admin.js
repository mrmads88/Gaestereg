(function () {
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const initials = (n) => String(n || "?").split(/\s+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";

let tenants = [], T = null, STATUS = null, tab = "people", lastField = null;

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
function showLogin() { $("appView").hidden = true; $("loginView").hidden = false; $("pw").focus(); }
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault(); $("loginErr").hidden = true;
  try { await api("POST", "/api/admin/login", { password: $("pw").value }); $("pw").value = ""; boot(); }
  catch (err) { $("loginErr").textContent = err.message; $("loginErr").hidden = false; }
});
$("logout").addEventListener("click", async () => { await api("POST", "/api/admin/logout").catch(() => {}); showLogin(); });

async function boot() {
  try { STATUS = await api("GET", "/api/admin/status"); } catch (e) { return; }
  $("loginView").hidden = true; $("appView").hidden = false;
  const env = STATUS.env;
  $("envPill").textContent = env === "prod" ? "Produktion" : env === "dev" ? "Dev" : "Lokal";
  $("envPill").className = "envpill " + env;
  const warn = [];
  if (STATUS.notify_mode !== "live") warn.push("Testtilstand: SMS og e-mails bliver logget under Besøg, men ikke sendt.");
  if (STATUS.default_password) warn.push("Standard-adgangskoden bruges. Sæt ADMIN_PASSWORD.");
  $("banner").textContent = warn.join(" "); $("banner").hidden = !warn.length;
  await loadTenants();
  const want = +(location.hash.replace("#t", "")) || (tenants[0] && tenants[0].id);
  if (want) selectTenant(want);
}

// ---------- tenant list ----------
async function loadTenants() { tenants = await api("GET", "/api/admin/tenants"); renderList(); }
function renderList() {
  $("tList").innerHTML = tenants.map((t) =>
    '<button class="titem" type="button" data-id="' + t.id + '" aria-current="' + (T && T.id === t.id) + '"><span class="tl">' +
    (t.logo_url ? '<img src="' + esc(t.logo_url) + '" alt="">' : '<i style="background:' + esc(t.color) + '"></i>') +
    '</span><span class="grow"><b>' + esc(t.name) + "</b><small>" + t.host_count + " personer" + (t.active ? "" : ' · <span class="off">slået fra</span>') + "</small></span></button>"
  ).join("") || '<p class="muted small">Ingen kunder endnu.</p>';
}
$("tList").addEventListener("click", (e) => { const b = e.target.closest("[data-id]"); if (b) selectTenant(+b.dataset.id); });
$("newTenant").addEventListener("click", () => { $("newForm").hidden = !$("newForm").hidden; if (!$("newForm").hidden) $("newName").focus(); });
$("newForm").addEventListener("submit", async (e) => {
  e.preventDefault(); const name = $("newName").value.trim(); if (!name) return;
  try {
    const t = await api("POST", "/api/admin/tenants", { name });
    $("newName").value = ""; $("newForm").hidden = true;
    await loadTenants(); selectTenant(t.id); setTab("look"); toast(name + " er oprettet. Upload logoet og tilføj personer.");
  } catch (err) { toast(err.message, true); }
});

async function selectTenant(id) {
  try { T = await api("GET", "/api/admin/tenants/" + id); } catch (err) { toast(err.message, true); return; }
  location.hash = "t" + id;
  $("noTenant").hidden = true; $("editor").hidden = false; $("pv").hidden = false;
  renderList(); renderAll(); loadPreview(true);
}
function upsertList() { const i = tenants.findIndex((x) => x.id === T.id); if (i > -1) tenants[i] = Object.assign({}, T, { host_count: T.hosts.length }); renderList(); }

// ---------- render editor ----------
function renderAll() { renderHead(); bindFields(); renderHosts(); renderImages(); renderMsg(); if (tab === "log") loadLog(); }
function renderHead() {
  document.documentElement.style.setProperty("--accent", T.color);
  $("edName").textContent = T.name;
  $("edLogo").innerHTML = T.logo_url ? '<img src="' + esc(T.logo_url) + '" alt="">' : "<span>" + esc(initials(T.name)) + "</span>";
  const url = location.origin + T.kiosk_url;
  $("kioskUrl").textContent = url; $("openKiosk").href = T.kiosk_url;
}
function bindFields() {
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
const FIELDS = [["vaert_fornavn", "værtens fornavn"], ["vaert", "værtens fulde navn"], ["gaest", "gæstens navn"], ["telefon", "gæstens mobil"], ["firma", "gæstens firma"], ["tid", "klokkeslæt"], ["kunde", "kundens navn"]];
const SAMPLE = { vaert_fornavn: "Anne", vaert: "Anne Kjær", gaest: "Mads Hansen", telefon: "+45 20 30 40 50", firma: "Hansen ApS", tid: "10:42", kunde: "" };
function fill(tpl) { return String(tpl || "").replace(/\{(\w+)\}/g, (m, k) => (k in SAMPLE ? (k === "kunde" ? T.name : SAMPLE[k]) : m)); }
function renderSample() {
  const sms = document.querySelector('[data-f="sms_template"]').value;
  const text = fill(sms);
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
    $("visitRows").innerHTML = v.map((x) => "<tr><td class=n>" + fmt(x.checked_in_at) + "</td><td>" + esc(x.guest_name) + "</td><td class=n>" + esc(x.guest_phone) + "</td><td>" + esc(x.guest_company) + "</td><td>" + esc(x.host_name) + "</td><td class=n>" + (x.checked_out_at ? fmt(x.checked_out_at).split(" ").pop() : "") + "</td></tr>").join("") || '<tr><td colspan="6" class="muted">Ingen besøg endnu.</td></tr>';
    $("noteRows").innerHTML = n.map((x) => "<tr><td class=n>" + fmt(x.created_at) + "</td><td>" + (x.channel === "sms" ? "SMS" : "E-mail") + "</td><td>" + esc(x.recipient) + '</td><td><span class="pill ' + esc(x.status) + '">' + esc(x.status) + "</span>" + (x.error ? '<div class="small" style="color:var(--bad)">' + esc(x.error) + "</div>" : "") + '</td><td><div class="body">' + esc(x.subject ? x.subject + "\n\n" + x.body : x.body) + "</div></td></tr>").join("") || '<tr><td colspan="5" class="muted">Ingen beskeder endnu.</td></tr>';
  } catch (err) { toast(err.message, true); }
}
$("refreshLog").addEventListener("click", loadLog);

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
