/* Tidsregistrering i admin (fanen "Tid" på et firma).
   NoddTime.mount(box, { tenant, api, toast, esc }) */
(function () {
  "use strict";
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const hm = (m) => (m < 0 ? "-" : "") + Math.floor(Math.abs(m) / 60) + ":" + pad(Math.abs(m) % 60);
  const hhmm = (s) => (s ? s.slice(11, 16) : "");
  const dayLong = (s) => new Date(s + "T12:00").toLocaleDateString("da-DK", { weekday: "long", day: "numeric", month: "long" });
  const span = (a) => { const d = new Date(a + "T12:00"), e = new Date(d); e.setDate(e.getDate() + 6);
    return d.getDate() + "." + (d.getMonth() !== e.getMonth() ? " " + d.toLocaleDateString("da-DK", { month: "short" }) : "") + "–" + e.toLocaleDateString("da-DK", { day: "numeric", month: "short", year: "numeric" }); };
  const addDays = (s, n) => { const d = new Date(s + "T12:00"); d.setDate(d.getDate() + n); return iso(d); };
  const fresh = (outer) => { const el = document.createElement("div"); el.className = "stack tm"; outer.replaceChildren(el); return el; };

  function mount(outer, o) {
    const box = fresh(outer);
    const { api, toast, esc } = o;
    const tid = o.tenant.id;
    let view = "week", monday = null, W = null, sel = null, pinShown = null;

    async function load() {
      try { W = await api("GET", "/api/admin/tenants/" + tid + "/time/week" + (monday ? "?monday=" + monday : "")); }
      catch (err) { box.innerHTML = '<p class="muted">' + esc(err.message) + "</p>"; return; }
      monday = W.monday; render();
    }
    const tabs = () => '<div class="row"><div class="seg"><button type="button" data-act="view" data-view="week" aria-pressed="' + (view === "week") + '">Uge</button>' +
      '<button type="button" data-act="view" data-view="staff" aria-pressed="' + (view === "staff") + '">Medarbejdere og opsætning</button></div></div>';

    function render() { box.innerHTML = tabs() + (view === "week" ? week() : staff()); }

    // ---------- uge ----------
    function week() {
      const rows = W.rows.filter((r) => r.has || !r.former);
      const allOk = rows.length && rows.filter((r) => r.has).every((r) => r.approved) && rows.some((r) => r.has);
      const head = '<div class="card"><div class="row tm-head"><button class="btn ghost sm" type="button" data-act="prev" aria-label="Forrige uge">‹</button>' +
        "<h3>Uge " + W.week + ' <small class="muted">' + esc(span(W.monday)) + '</small></h3><button class="btn ghost sm" type="button" data-act="next" aria-label="Næste uge">›</button>' +
        '<button class="btn ghost sm" type="button" data-act="now">Denne uge</button><span class="grow"></span>' +
        (rows.some((r) => r.has) ? '<button class="btn ' + (allOk ? "ghost" : "pri") + ' sm" type="button" data-act="' + (allOk ? "reopen" : "approve") + '">' + (allOk ? "Genåbn ugen" : "Godkend ugen") + "</button>" : "") + "</div>" +
        (W.missing ? '<p class="tm-warn">' + W.missing + (W.missing === 1 ? " stempling mangler" : " stemplinger mangler") + " udstempling. Tryk på dagen og ret tiden.</p>" : "") +
        (W.inside.length ? '<div class="tm-inside"><b>På arbejde nu</b>' + W.inside.map((x) => "<span>" + esc(x.name) + " <small>siden " + esc(x.since_hhmm) + "</small></span>").join("") + "</div>" : "") +
        (rows.length ? '<div class="tablewrap"><table class="tm-table"><thead><tr><th>Medarbejder</th>' + W.days.map((d) => '<th class="n' + (d.today ? " today" : "") + '">' + esc(d.label) + "</th>").join("") +
          '<th class="n">I alt</th><th class="n">Norm</th><th class="n">±</th><th></th></tr></thead><tbody>' +
          rows.map((r) => "<tr><td><b>" + esc(r.name) + "</b>" + (r.former ? '<small class="muted">ikke længere aktiv</small>' : "") + "</td>" +
            r.days.map((m, i) => { const miss = r.entries.some((e) => e.day === W.days[i].date && e.stale), open = r.entries.some((e) => e.day === W.days[i].date && e.open && !e.stale);
              const on = sel && sel.host === r.host_id && sel.day === i;
              return '<td class="n"><button type="button" class="tm-cell' + (on ? " on" : "") + (miss ? " miss" : "") + '" data-act="cell" data-host="' + r.host_id + '" data-day="' + i + '">' + (m ? hm(m) : "–") + (open ? ' <i class="tm-live" title="Stemplet ind"></i>' : "") + (miss ? " !" : "") + "</button></td>"; }).join("") +
            '<td class="n"><b>' + (r.total ? hm(r.total) : "–") + '</b></td><td class="n muted">' + (r.norm ? hm(r.norm) : "–") + '</td><td class="n ' + (r.diff > 0 ? "tm-plus" : r.diff < 0 ? "tm-minus" : "") + '">' + (r.diff == null || !r.has ? "–" : (r.diff > 0 ? "+" : "") + hm(r.diff)) + "</td>" +
            "<td>" + (r.has ? '<span class="pill ' + (r.approved ? "sendt" : "venter") + '">' + (r.approved ? "Godkendt" : "Åben") + "</span>" : "") + "</td></tr>").join("") + "</tbody></table></div>"
          : '<p class="muted small">Ingen medarbejdere registrerer tid endnu. Slå det til under <b>Medarbejdere og opsætning</b>.</p>') + "</div>";
      return head + (sel ? day() : "") + exportCard();
    }
    function day() {
      const r = W.rows.find((x) => x.host_id === sel.host); if (!r) return "";
      const date = W.days[sel.day].date;
      const es = r.entries.filter((e) => e.day === date);
      const locked = (e) => e.approved;
      return '<div class="card tm-day"><div class="row"><h3 class="grow">' + esc(r.name) + ' <small class="muted">' + esc(dayLong(date)) + '</small></h3><button class="btn ghost sm" type="button" data-act="close">Luk</button></div>' +
        (es.length ? es.map((e) => '<form class="tm-entry" data-form="edit" data-eid="' + e.id + '">' +
          '<label class="fld"><span>Ind</span><input type="time" name="start" value="' + hhmm(e.start) + '" required' + (locked(e) ? " disabled" : "") + "></label>" +
          '<label class="fld"><span>Ud' + (e.stale ? ' <b class="tm-minus">mangler</b>' : e.open ? " (stemplet ind)" : "") + '</span><input type="time" name="end" value="' + hhmm(e.end) + '"' + (locked(e) ? " disabled" : "") + "></label>" +
          '<label class="fld"><span>Pause, min.</span><input type="number" name="break_min" min="0" max="600" value="' + e.break_min + '"' + (locked(e) ? " disabled" : "") + "></label>" +
          '<label class="fld grow"><span>Note</span><input name="note" maxlength="300" value="' + esc(e.note) + '"' + (locked(e) ? " disabled" : "") + "></label>" +
          '<div class="tm-acts">' + (locked(e) ? '<span class="pill sendt">Godkendt</span>' : '<button class="btn pri sm" type="submit">Gem</button><button class="btn ghost sm" type="button" data-act="del">Slet</button>') + "</div>" +
          '<p class="tm-meta">' + esc(hm(e.minutes)) + " · " + ({ kiosk: "stemplet på skærmen", phone: "stemplet på telefonen", admin: "oprettet i admin" }[e.source] || e.source) +
          (e.edits.filter((x) => x.what !== "oprettet").length ? " · " + e.edits.filter((x) => x.what !== "oprettet").map((x) => esc(x.what) + " af " + esc(x.by) + " " + esc(new Date(x.at).toLocaleString("da-DK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }))).join(", ") : "") + "</p></form>").join("")
          : '<p class="muted small">Ingen registreringer denne dag.</p>') +
        '<form class="tm-entry tm-add" data-form="add"><label class="fld"><span>Ind</span><input type="time" name="start" required></label><label class="fld"><span>Ud</span><input type="time" name="end"></label>' +
        '<label class="fld"><span>Pause, min.</span><input type="number" name="break_min" min="0" max="600" value="0"></label><label class="fld grow"><span>Note</span><input name="note" maxlength="300" placeholder="Fx glemt at stemple"></label>' +
        '<div class="tm-acts"><button class="btn ghost sm" type="submit">Tilføj</button></div></form>' +
        '<p class="muted small">Alle rettelser gemmes med navn og tidspunkt. Medarbejderen kan se dem på sin telefon.</p></div>';
    }
    function exportCard() {
      const m = W.monday.slice(0, 7);
      return '<div class="card"><h3>Eksport til løn</h3><p class="muted small">CSV med ind, ud, pause og timer pr. dag og en sum pr. medarbejder. Kan læses af Excel, Danløn og Salary.</p>' +
        '<form class="row tm-export" data-form="export"><label class="fld"><span>Måned</span><input type="month" name="month" value="' + m + '" required></label><button class="btn ghost sm" type="submit">Hent CSV</button></form></div>';
    }

    // ---------- medarbejdere og opsætning ----------
    function staff() {
      const s = W.settings;
      return '<div class="card"><h3>Opsætning</h3><form class="stack" data-form="settings">' +
        '<label class="check"><input type="checkbox" name="time_kiosk"' + (s.time_kiosk ? " checked" : "") + '> Vis knappen <b>Medarbejder</b> på gæsteskærmen (stempl ind og ud med PIN)</label>' +
        '<label class="fld tm-narrow"><span>Automatisk pause ved dage over 6 timer (minutter)</span><input type="number" name="time_break_min" min="0" max="120" value="' + s.time_break_min + '"><small class="hint">0 = ingen. Trækkes fra, når medarbejderen stempler ud.</small></label>' +
        '<div class="row"><button class="btn pri sm" type="submit">Gem</button></div></form></div>' +
        '<div class="card"><h3>Medarbejdere</h3><p class="muted small">Slå tidsregistrering til for dem, der skal stemple. Hver får en 4-cifret PIN til skærmen og et personligt link til telefonen, hvor de også kan se deres egne registreringer. Registreringerne gemmes i 5 år, som loven kræver.</p>' +
        (pinShown ? '<div class="tm-pin">PIN til <b>' + esc(pinShown.name) + "</b>: <code>" + esc(pinShown.pin) + "</code><small>Giv den til medarbejderen nu. Den vises ikke igen.</small></div>" : "") +
        (W.staff.length ? '<div class="tablewrap"><table class="tm-table tm-staff"><thead><tr><th>Person</th><th>Registrerer tid</th><th>Normtid pr. uge</th><th>PIN</th><th></th></tr></thead><tbody>' +
          W.staff.map((h) => '<tr data-hid="' + h.id + '"><td><b>' + esc(h.name) + "</b>" + (h.title ? "<small class=\"muted\">" + esc(h.title) + "</small>" : "") + "</td>" +
            '<td><input type="checkbox" data-act="enable" aria-label="Registrerer tid"' + (h.time_enabled ? " checked" : "") + "></td>" +
            '<td><input class="tm-norm" type="number" min="0" max="60" step="0.25" data-act="norm" aria-label="Timer pr. uge" value="' + (h.time_norm_min ? h.time_norm_min / 60 : "") + '" placeholder="fx 37"> timer</td>' +
            "<td>" + (h.has_pin ? '<span class="pill sendt">Sat</span>' : '<span class="pill test">Ingen</span>') + ' <button class="btn ghost sm" type="button" data-act="pin">Ny PIN</button></td>' +
            "<td>" + (h.time_enabled ? '<button class="btn ghost sm" type="button" data-act="link">Kopiér telefonlink</button>' : "") + "</td></tr>").join("") + "</tbody></table></div>"
          : '<p class="muted small">Tilføj personerne under fanen Personer først.</p>') + "</div>";
    }

    // ---------- handlinger ----------
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      const act = b.dataset.act;
      try {
        if (act === "view") { view = b.dataset.view; pinShown = null; await load(); }
        else if (act === "prev") { monday = addDays(monday, -7); sel = null; await load(); }
        else if (act === "next") { monday = addDays(monday, 7); sel = null; await load(); }
        else if (act === "now") { monday = null; sel = null; await load(); }
        else if (act === "cell") { const h = +b.dataset.host, d = +b.dataset.day; sel = sel && sel.host === h && sel.day === d ? null : { host: h, day: d }; render(); }
        else if (act === "close") { sel = null; render(); }
        else if (act === "approve" || act === "reopen") {
          const r = await api("POST", "/api/admin/tenants/" + tid + "/time/approve", { monday: W.monday, approve: act === "approve" });
          toast(act === "approve" ? "Ugen er godkendt (" + r.changed + " registreringer)" : "Ugen er genåbnet"); await load();
        } else if (act === "del") {
          if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Slet"; }, 3500); return; }
          await api("DELETE", "/api/admin/time/entries/" + b.closest("[data-eid]").dataset.eid); toast("Slettet"); await load();
        } else if (act === "pin") {
          const hid = b.closest("[data-hid]").dataset.hid;
          pinShown = await api("POST", "/api/admin/hosts/" + hid + "/time/pin"); await load();
        } else if (act === "link") {
          const r = await api("GET", "/api/admin/hosts/" + b.closest("[data-hid]").dataset.hid + "/time/link");
          const url = location.origin + r.path;
          (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(() => toast("Link kopieret. Send det til medarbejderen."), () => toast(url));
        }
      } catch (err) { toast(err.message, true); }
    });
    box.addEventListener("change", async (e) => {
      const el = e.target, row = el.closest("[data-hid]"); if (!row) return;
      try {
        if (el.dataset.act === "enable") { await api("PATCH", "/api/admin/hosts/" + row.dataset.hid + "/time", { time_enabled: el.checked }); toast(el.checked ? "Slået til" : "Slået fra"); await load(); }
        else if (el.dataset.act === "norm") { await api("PATCH", "/api/admin/hosts/" + row.dataset.hid + "/time", { time_norm_min: Math.round((parseFloat(String(el.value).replace(",", ".")) || 0) * 60) }); toast("Normtid gemt"); }
      } catch (err) { toast(err.message, true); }
    });
    box.addEventListener("submit", async (e) => {
      const f = e.target.closest("form[data-form]"); if (!f) return;
      e.preventDefault();
      const v = Object.fromEntries(new FormData(f).entries());
      try {
        if (f.dataset.form === "export") {
          const [y, m] = v.month.split("-").map(Number);
          const last = new Date(y, m, 0).getDate();
          location.href = "/api/admin/tenants/" + tid + "/time/export.csv?start=" + v.month + "-01&end=" + v.month + "-" + pad(last);
          return;
        }
        if (f.dataset.form === "settings") {
          await api("PATCH", "/api/admin/tenants/" + tid + "/time/settings", { time_kiosk: !!f.time_kiosk.checked, time_break_min: +v.time_break_min || 0 });
          toast("Gemt"); await load(); return;
        }
        const date = W.days[sel.day].date;
        const end = v.end ? (v.end <= v.start ? addDays(date, 1) : date) + "T" + v.end : null; // ud efter midnat = næste dag
        const body = { start: date + "T" + v.start, end, break_min: +v.break_min || 0, note: v.note || "" };
        if (f.dataset.form === "add") { await api("POST", "/api/admin/tenants/" + tid + "/time/entries", { host_id: sel.host, ...body }); toast("Tilføjet"); }
        else { await api("PATCH", "/api/admin/time/entries/" + f.dataset.eid, body); toast("Rettet. Rettelsen er gemt i loggen."); }
        await load();
      } catch (err) { toast(err.message, true); }
    });

    load();
  }

  window.NoddTime = { mount };
})();
