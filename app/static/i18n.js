/* Sprog i admin og på medarbejdernes sider (tid, booking, køkken, rapport, evakuering).

   Dansk er kildeteksten. Er sproget engelsk, oversættes teksten på siden med ordbogen i i18n-en.js:
   - hele tekster (fx en knap: "Gem" → "Save"),
   - faste mønstre (NODD_EN_PATTERNS, fx "3 af 10"),
   - stykker, som JavaScript sætter sammen med tal og navne (fx " personer" i n + " personer").
   En MutationObserver oversætter også det, der tegnes senere (lister, toasts, fejlbeskeder fra serveren).
   På dansk gør scriptet ingenting.

   Sproget: ?lang=da|en, ellers det gemte valg (localStorage), ellers dansk i admin og browserens sprog på
   medarbejdernes sider. I admin gemmes valget også på brugeren (User.lang), så det følger med til andre enheder.
   Elementer med translate="no" (fx sprogknappen) oversættes ikke. */
(function () {
  "use strict";
  const KEY = "nodd-lang";
  const ADMIN = /^\/admin/.test(location.pathname);
  function pick() {
    const q = new URLSearchParams(location.search).get("lang");
    if (q === "da" || q === "en") return q;
    try { const s = localStorage.getItem(KEY); if (s === "da" || s === "en") return s; } catch (e) { /* privat tilstand */ }
    if (ADMIN) return "da";
    return /^da\b/i.test(navigator.language || "da") ? "da" : "en";
  }
  const lang = pick();
  const D = window.NODD_EN || {};
  const has = (k) => Object.prototype.hasOwnProperty.call(D, k);
  const PATTERNS = (window.NODD_EN_PATTERNS || []).map(([p, r]) => [new RegExp("^" + p + "$", "u"), r]);
  // Stykker, der må erstattes inde i en længere tekst: flere ord, eller et enkelt ord med små bogstaver på mindst 5 tegn.
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pieces = Object.keys(D).filter((k) => D[k] !== k && (/\s/.test(k) ? k.length >= 4
    : /^[a-zæøå][a-zæøå-]{4,}$/.test(k) || (/\./.test(k) && k.length >= 4 && /^[\p{L}/.()]+$/u.test(k))))
    .sort((a, b) => b.length - a.length);
  // Ordgrænser kun, hvor stykket starter eller slutter med et bogstav eller tal (". Se Fakturering." kan stå lige efter et ord).
  const edge = (k) => (/^[\p{L}\p{N}]/u.test(k) ? "(?<![\\p{L}\\p{N}])" : "") + esc(k) + (/[\p{L}\p{N}]$/u.test(k) ? "(?![\\p{L}\\p{N}])" : "");
  const FRAG = pieces.length ? new RegExp(pieces.map(edge).join("|"), "gu") : null;

  function tr(s) {
    if (lang !== "en" || s == null) return s;
    const str = String(s), t = str.trim();
    if (!t || !/\p{L}/u.test(t)) return str;
    if (has(t)) return str.replace(t, () => D[t]);
    for (const [r, rep] of PATTERNS) if (r.test(t)) return str.replace(t, () => t.replace(r, rep));
    return FRAG ? str.replace(FRAG, (m) => (has(m) ? D[m] : m)) : str;
  }

  const ATTRS = ["placeholder", "title", "aria-label", "alt"];
  const SKIP = "script,style,textarea,code,[translate=no],[contenteditable]";
  const HARD = "script,style,code,[translate=no],[contenteditable]"; // tekstfelter: kun placeholder og title
  function translate(n) {
    if (n.nodeType === 3) {
      const p = n.parentElement;
      if (!p || p.closest(SKIP)) return;
      const v = tr(n.nodeValue);
      if (v !== n.nodeValue) n.nodeValue = v;
      return;
    }
    if (n.nodeType !== 1 || n.closest(HARD)) return;
    for (const a of ATTRS) {
      const v = n.getAttribute(a);
      if (v) { const x = tr(v); if (x !== v) n.setAttribute(a, x); }
    }
    if (n.tagName === "INPUT" && (n.type === "button" || n.type === "submit") && n.value) n.value = tr(n.value);
    if (n.tagName === "TEXTAREA") return;
    for (let c = n.firstChild; c; c = c.nextSibling) translate(c);
  }

  function start() {
    document.documentElement.lang = "en";
    translate(document.body);
    document.title = tr(document.title);
    new MutationObserver((list) => {
      for (const m of list) {
        if (m.type === "characterData") translate(m.target);
        else if (m.type === "attributes") translate(m.target);
        else m.addedNodes.forEach(translate);
      }
    }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }

  function set(l) { try { localStorage.setItem(KEY, l); } catch (e) { /* privat tilstand */ } }

  window.NODD_I18N = { lang, tr, set, loc: () => (lang === "en" ? "en-GB" : "da-DK") };
  // Datoer og tal formateres efter sproget (bruges i stedet for "da-DK").
  window.NODD_LOC = () => (lang === "en" ? "en-GB" : "da-DK");
  if (lang === "en") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
  }
})();
