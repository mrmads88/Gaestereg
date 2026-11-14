/* Nødbesked på skærmene (gæsteskærm /k/, lokaleskærm /room/, infoskærm /s/).
   Spørger serveren hvert 15. sekund (svaret kommer fra hukommelsen). Evakuering og advarsel dækker hele skærmen;
   information vises som et bånd øverst, så skærmen stadig kan bruges. */
(function () {
  "use strict";
  const m = location.pathname.match(/^\/(k|room|s)\/([^/?#]+)/);
  if (!m) return;
  const kind = m[1], token = decodeURIComponent(m[2]);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = document.createElement("style");
  css.textContent = [
    ".nodd-alert{position:fixed;inset:0;z-index:2147483646;display:flex;flex-direction:column;justify-content:center;gap:2.4vh;",
    "padding:6vh 7vw;color:#fff;font-family:'Hanken Grotesk',system-ui,-apple-system,'Segoe UI',sans-serif;cursor:default}",
    ".nodd-alert.evacuation{background:#b42318}.nodd-alert.warning{background:#a14f00}",
    ".nodd-alert::before{content:'';position:absolute;inset:1.6vh;border:1vh solid rgb(255 255 255 / .9);border-radius:2vh;animation:nodd-pulse 1.4s ease-in-out infinite}",
    "@keyframes nodd-pulse{50%{opacity:.25}}",
    ".nodd-alert .ico{width:clamp(64px,13vh,180px);height:clamp(64px,13vh,180px)}",
    ".nodd-alert h1{margin:0;font:800 clamp(40px,11vh,160px)/1 'Bricolage Grotesque',system-ui,sans-serif;letter-spacing:-.02em}",
    ".nodd-alert p{margin:0;font-size:clamp(20px,4.2vh,56px);line-height:1.3;max-width:34em;white-space:pre-line}",
    ".nodd-alert small{font-size:clamp(14px,2.2vh,28px);opacity:.85}",
    ".nodd-band{position:fixed;left:0;right:0;top:0;z-index:2147483646;background:#1f4f9a;color:#fff;display:flex;gap:16px;align-items:center;",
    "padding:14px 22px;font:600 clamp(15px,2.2vh,30px)/1.3 'Hanken Grotesk',system-ui,sans-serif;box-shadow:0 6px 20px rgb(0 0 0 / .25)}",
    ".nodd-band b{white-space:nowrap}",
    "html.nodd-banded body{padding-top:var(--nodd-band,56px)!important;box-sizing:border-box}",
    "@media (prefers-reduced-motion:reduce){.nodd-alert::before{animation:none}}",
  ].join("");
  document.head.appendChild(css);
  const ICON = '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>';
  let el = null, shown = "";

  function render(a) {
    const key = a ? a.id + ":" + a.kind + ":" + a.title + ":" + a.message : "";
    if (key === shown) return;
    shown = key;
    if (el) { el.remove(); el = null; }
    document.documentElement.classList.remove("nodd-banded");
    window.NoddAlert = a || null;
    if (!a) return;
    const st = a.started_at ? new Date(a.started_at) : null;
    const since = st ? String(st.getHours()).padStart(2, "0") + ":" + String(st.getMinutes()).padStart(2, "0") : "";
    el = document.createElement("div");
    el.setAttribute("role", "alert");
    el.setAttribute("aria-live", "assertive");
    if (a.kind === "info") {
      el.className = "nodd-band";
      el.innerHTML = "<b>" + esc(a.title) + "</b><span>" + esc(a.message) + "</span>";
    } else {
      el.className = "nodd-alert " + a.kind;
      el.innerHTML = ICON + "<h1>" + esc(a.title) + "</h1>" + (a.message ? "<p>" + esc(a.message) + "</p>" : "") + (since ? "<small>Siden kl. " + since + "</small>" : "");
      // Skærmen må ikke kunne bruges, mens beskeden vises.
      ["click", "touchstart", "keydown"].forEach((ev) => el.addEventListener(ev, (e) => { e.stopPropagation(); e.preventDefault(); }, true));
    }
    document.body.appendChild(el);
    if (a.kind === "info") {  // skub skærmens indhold ned, så båndet ikke dækker noget
      document.documentElement.style.setProperty("--nodd-band", el.offsetHeight + "px");
      document.documentElement.classList.add("nodd-banded");
    }
  }

  async function poll() {
    try {
      const r = await fetch("/api/alert/" + kind + "/" + encodeURIComponent(token), { cache: "no-store" });
      if (r.ok) render((await r.json()).alert);
    } catch (e) { /* uden net: behold det, der vises */ }
  }
  poll();
  setInterval(poll, 15000);
})();
