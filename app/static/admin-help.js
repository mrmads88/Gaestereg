/* "?"-hjælp i admin: et lille spørgsmålstegn ved overskrifterne, der har et tip i help-content.js (NODD_HELP.tips).
   Holder man musen over (eller trykker på telefonen), vises en kort forklaring og et link til guiden i hjælpecentret.
   Overskrifterne findes på deres danske tekst (eller den engelske oversættelse), også dem der tegnes senere. */
(function () {
  "use strict";
  const H = window.NODD_HELP; if (!H) return;
  const lang = (window.NODD_I18N && window.NODD_I18N.lang) || "da";
  const EN = window.NODD_EN || {};
  const byText = new Map();
  for (const [da, tip] of Object.entries(H.tips)) { byText.set(da, tip); if (EN[da]) byText.set(EN[da], tip); }
  const L = (o) => (o && (o[lang] || o.da)) || "";
  const helpUrl = (id) => "/hjaelp?lang=" + lang + (id ? "#" + id : "");

  const pop = document.createElement("div");
  pop.className = "help-pop"; pop.hidden = true; pop.setAttribute("role", "tooltip"); pop.setAttribute("translate", "no"); pop.id = "helpPop";
  document.body.appendChild(pop);
  let cur = null, hideT = null;

  function label(el) { return Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.nodeValue).join("").trim(); }
  function attach(root) {
    const els = root.querySelectorAll ? root.querySelectorAll("h2, h3, .lbl, .fld > span") : [];
    for (const el of [root, ...els]) {
      if (!el.matches || !el.matches("h2, h3, .lbl, .fld > span") || el.querySelector(".help-q")) continue;
      const tip = byText.get(label(el)); if (!tip) continue;
      const b = document.createElement("button");
      b.type = "button"; b.className = "help-q"; b.textContent = "?"; b.setAttribute("translate", "no");
      b.setAttribute("aria-label", lang === "en" ? "Help" : "Hjælp"); b.setAttribute("aria-describedby", "helpPop");
      b._tip = tip;
      el.appendChild(b);
    }
  }
  function show(b) {
    clearTimeout(hideT); cur = b;
    const t = b._tip, g = H.guides.find((x) => x.id === t.guide);
    pop.innerHTML = "<p></p>" + (g ? '<a target="_blank" rel="noopener"></a>' : "");
    pop.querySelector("p").textContent = L(t);
    if (g) { const a = pop.querySelector("a"); a.href = helpUrl(g.id); a.textContent = (lang === "en" ? "Read the guide: " : "Læs guiden: ") + L(g.title) + " →"; }
    pop.hidden = false;
    const r = b.getBoundingClientRect(), w = Math.min(320, window.innerWidth - 24);
    pop.style.width = w + "px";
    const left = Math.max(12, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - 12));
    const below = r.bottom + 8 + pop.offsetHeight < window.innerHeight;
    pop.style.left = left + "px";
    pop.style.top = (below ? r.bottom + 8 : r.top - 8 - pop.offsetHeight) + window.scrollY + "px";
  }
  function hide(now) { clearTimeout(hideT); hideT = setTimeout(() => { pop.hidden = true; cur = null; }, now ? 0 : 180); }

  document.addEventListener("mouseover", (e) => { const b = e.target.closest(".help-q"); if (b) show(b); else if (cur && !e.target.closest(".help-pop")) hide(); });
  document.addEventListener("focusin", (e) => { const b = e.target.closest(".help-q"); if (b) show(b); });
  document.addEventListener("focusout", (e) => { if (e.target.closest(".help-q") && !pop.contains(e.relatedTarget)) hide(); });
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".help-q");
    if (b) { e.preventDefault(); e.stopPropagation(); if (cur === b && !pop.hidden) hide(true); else show(b); return; }
    if (!e.target.closest(".help-pop")) hide(true);
  }, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(true); });
  window.addEventListener("scroll", () => hide(true), { passive: true });

  attach(document.body);
  new MutationObserver((list) => { for (const m of list) m.addedNodes.forEach((n) => n.nodeType === 1 && attach(n)); })
    .observe(document.body, { childList: true, subtree: true });
  window.NoddHelp = { url: helpUrl };
})();
