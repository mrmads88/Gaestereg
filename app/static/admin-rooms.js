/* Mødelokaler i admin (fase 5a). Bruges både i firmaets fane "Lokaler" og på partnerens (husets) side.
   NoddRooms.mount(box, { scope: {tenant_id} | {partner_id}, api, toast, esc, firms, privacy, onPrivacy }) */
(function () {
  "use strict";
  const PRIV = [["busy", "Kun ledigt/optaget"], ["organizer", "Arrangør og firma"], ["title", "Mødets titel, arrangør og firma"]];
  const pad = (n) => String(n).padStart(2, "0");
  const isoDay = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  const hm = (s) => { const d = new Date(s); return pad(d.getHours()) + ":" + pad(d.getMinutes()); };
  const list = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);

  function mount(box, o) {
    const { api, toast, esc } = o;
    const q = o.scope.tenant_id ? "tenant_id=" + o.scope.tenant_id : "partner_id=" + o.scope.partner_id;
    const isHouse = !!o.scope.partner_id;
    let rooms = [], editing = null, day = isoDay(new Date());

    const inheritLabel = isHouse ? "Standard: kun ledigt/optaget" : "Som huset bestemmer (ellers kun ledigt/optaget)";
    box.innerHTML =
      '<div class="card"><div class="row"><h3 class="grow">Bookinger</h3><input type="date" class="rm-day" aria-label="Dato">' +
      '<button class="btn pri sm" type="button" data-newbook>+ Ny booking</button></div>' +
      '<form class="rm-book" hidden autocomplete="off"><div class="g2"><label class="fld"><span>Lokale</span><select name="room_id" required></select></label>' +
      (isHouse ? '<label class="fld"><span>Firma</span><select name="tenant_id" required></select></label>' : '<label class="fld"><span>Mødets titel</span><input name="title" maxlength="200"></label>') + "</div>" +
      (isHouse ? '<label class="fld"><span>Mødets titel</span><input name="title" maxlength="200"></label>' : "") +
      '<div class="g4"><label class="fld"><span>Dato</span><input name="date" type="date" required></label><label class="fld"><span>Fra</span><input name="start" type="time" step="900" required></label>' +
      '<label class="fld"><span>Til</span><input name="end" type="time" step="900" required></label><label class="fld"><span>Deltagere</span><input name="attendees" type="number" min="0" max="1000" value="0"></label></div>' +
      '<div class="row"><span class="grow muted small">Personerne kan også selv booke via deres personlige link (fanen Forventede gæster).</span><button class="btn ghost sm" type="button" data-cancelform>Fortryd</button><button class="btn pri sm" type="submit">Book</button></div></form>' +
      '<div class="tablewrap"><table><thead><tr><th>Tid</th><th>Lokale</th><th>Møde</th><th>Booket af</th><th>Pers.</th><th></th></tr></thead><tbody class="rm-rows"></tbody></table></div></div>' +

      '<div class="card"><div class="row"><h3 class="grow">' + (isHouse ? "Husets mødelokaler" : "Mødelokaler") + '</h3><button class="btn pri sm" type="button" data-newroom>+ Nyt lokale</button></div>' +
      '<p class="muted small">' + (isHouse ? "Alle firmaer i huset kan booke husets lokaler. Hvert lokale har sin egen skærm ved døren, der viser ledigt (grøn) eller optaget (rød)."
        : "Firmaets egne lokaler. Husets fælles lokaler vises også her og kan bookes, men rettes af huset.") + "</p>" +
      '<form class="rm-edit card inset" hidden autocomplete="off"><h3 class="rm-edit-h"></h3>' +
      '<div class="g2"><label class="fld"><span>Navn</span><input name="name" required maxlength="120" placeholder="Fx Store sal"></label>' +
      '<label class="fld"><span>Placering</span><input name="location" maxlength="120" placeholder="Fx 2. sal, ved køkkenet"></label></div>' +
      '<div class="g2"><label class="fld"><span>Pladser</span><input name="capacity" type="number" min="0" max="1000"></label>' +
      '<label class="fld"><span>Hvad må skærmen ved døren vise?</span><select name="privacy"><option value="">' + esc(isHouse ? "Som firmaet, der booker, eller huset" : "Som firmaet bestemmer") + "</option>" +
      PRIV.map((p) => '<option value="' + p[0] + '">' + esc(p[1]) + "</option>").join("") + "</select></label></div>" +
      '<label class="fld"><span>Beskrivelse</span><textarea name="description" rows="2" maxlength="500" placeholder="Fx lyst lokale med udsigt over havnen"></textarea></label>' +
      '<div class="g2"><label class="fld"><span>Opstillinger</span><input name="setups" maxlength="600" placeholder="Fx Bord, Hestesko, Biograf"><small class="hint">Adskil med komma. Den, der booker, vælger én.</small></label>' +
      '<label class="fld"><span>Udstyr</span><input name="equipment" maxlength="900" placeholder="Fx Skærm, Tavle, Videomøde"><small class="hint">Adskil med komma. Kan vælges til ved booking.</small></label></div>' +
      '<div class="row rm-only-edit"><span class="rm-photo"></span><label class="btn ghost sm file">Upload billede<input type="file" accept="image/*" name="photo"></label>' +
      '<label class="switch"><input type="checkbox" name="active"><i></i><em>Kan bookes</em></label></div>' +
      '<div class="row"><button class="btn bad sm rm-only-edit" type="button" data-delroom>Slet lokale</button><span class="grow"></span><button class="btn ghost sm" type="button" data-closeedit>Luk</button><button class="btn pri sm" type="submit">Gem</button></div></form>' +
      '<div class="rm-grid"></div></div>' +

      '<div class="card"><h3>Diskretion på lokaleskærmene</h3><p class="muted small">Hvad må andre se om ' + (isHouse ? "firmaernes" : "jeres") +
      ' møder på skærmen ved døren og på bookingsiden? Fx skal "Fyringsrunde" ikke stå til skue. ' +
      (isHouse ? "Gælder alle husets lokaler, medmindre et firma eller en skærm har sin egen indstilling." : "Gælder jeres møder i alle lokaler, medmindre den enkelte skærm har sin egen indstilling.") +
      '</p><label class="fld"><span>Vis</span><select class="rm-priv"><option value="">' + esc(inheritLabel) + "</option>" +
      PRIV.map((p) => '<option value="' + p[0] + '">' + esc(p[1]) + "</option>").join("") + "</select></label></div>";

    const $$ = (s) => box.querySelector(s);
    const bookForm = $$(".rm-book"), editForm = $$(".rm-edit");
    $$(".rm-day").value = day;
    $$(".rm-priv").value = o.privacy || "";

    async function load() {
      try { rooms = await api("GET", "/api/admin/rooms?" + q); } catch (err) { toast(err.message, true); return; }
      renderRooms(); loadBookings();
    }

    function renderRooms() {
      $$(".rm-grid").innerHTML = rooms.map((r) => '<div class="rm-card' + (r.active ? "" : " off") + '" data-rid="' + r.id + '">' +
        '<div class="rm-ph">' + (r.photo_url ? '<img src="' + esc(r.photo_url) + '" alt="">' : "<span>" + esc(r.name.slice(0, 1)) + "</span>") + "</div>" +
        '<div class="rm-b"><b>' + esc(r.name) + (r.partner_id && !isHouse ? '<span class="tag house">Husets</span>' : "") + (r.active ? "" : '<span class="tag">Slået fra</span>') +
        "</b><small class=muted>" + esc([r.capacity ? r.capacity + " pladser" : "", r.location].filter(Boolean).join(" · ")) + "</small>" +
        '<div class="row">' + (r.can_manage ? '<button class="btn ghost sm" type="button" data-edit>Ret</button>' : "") +
        '<a class="btn ghost sm" target="_blank" rel="noopener" href="' + esc(r.screen_url) + '">Åbn skærm</a>' +
        (r.can_manage ? '<button class="btn ghost sm" type="button" data-copy>Kopiér skærmlink</button>' : "") + "</div></div></div>").join("") ||
        '<p class="muted">Ingen lokaler endnu. Opret det første, så kan personerne booke det.</p>';
      const sel = bookForm.room_id, cur = sel.value;
      sel.innerHTML = rooms.filter((r) => r.active).map((r) => '<option value="' + r.id + '">' + esc(r.name) + (r.capacity ? " (" + r.capacity + ")" : "") + "</option>").join("");
      if (cur) sel.value = cur;
    }

    async function loadBookings() {
      let rows;
      try { rows = await api("GET", "/api/admin/bookings?" + q + "&date=" + day); } catch (err) { toast(err.message, true); return; }
      const name = (id) => (rooms.find((r) => r.id === id) || {}).name || "";
      $$(".rm-rows").innerHTML = rows.map((b) => '<tr data-bid="' + b.id + '"><td class="n">' + hm(b.start) + "–" + hm(b.end) + "</td><td>" + esc(name(b.room_id)) +
        "</td><td>" + esc(b.title || "Møde") + (b.full && b.setup ? '<div class="small muted">' + esc([b.setup, ...(b.equipment || [])].join(" · ")) + "</div>" : "") +
        (b.full && b.note ? '<div class="small muted">' + esc(b.note) + "</div>" : "") + "</td><td>" + esc([b.organizer, b.firm].filter(Boolean).join(", ")) +
        (b.source === "screen" ? '<div class="small muted">på skærmen</div>' : "") + '</td><td class="n">' + (b.full && b.attendees ? b.attendees : "") +
        '</td><td><button class="btn ghost sm" type="button" data-cancelbook>Aflys</button></td></tr>').join("") ||
        '<tr><td colspan="6" class="muted">Ingen bookinger denne dag.</td></tr>';
    }

    function openEdit(r) {
      editing = r || null;
      editForm.hidden = false;
      $$(".rm-edit-h").textContent = r ? "Ret " + r.name : "Nyt lokale";
      box.querySelectorAll(".rm-only-edit").forEach((x) => (x.hidden = !r));
      editForm.name.value = r ? r.name : ""; editForm.location.value = r ? r.location : "";
      editForm.capacity.value = r && r.capacity ? r.capacity : ""; editForm.description.value = r ? r.description : "";
      editForm.setups.value = r ? r.setups.join(", ") : ""; editForm.equipment.value = r ? r.equipment.join(", ") : "";
      editForm.privacy.value = r ? r.privacy : ""; editForm.active.checked = r ? r.active : true;
      $$(".rm-photo").innerHTML = r && r.photo_url ? '<img src="' + esc(r.photo_url) + '" alt="">' : '<span class="muted small">Intet billede</span>';
      editForm.name.focus();
    }

    function nextSlot() {
      const d = new Date(); d.setMinutes(Math.ceil((d.getMinutes() + 1) / 15) * 15, 0, 0);
      const e = new Date(d.getTime() + 3600000);
      return [isoDay(d), hm(d), hm(e)];
    }

    box.addEventListener("click", async (e) => {
      const t = e.target;
      if (t.closest("[data-newbook]")) {
        bookForm.hidden = !bookForm.hidden;
        if (!bookForm.hidden) {
          const [d, s, en] = nextSlot();
          bookForm.date.value = day < d ? d : day; bookForm.start.value = s; bookForm.end.value = en;
          if (isHouse) bookForm.tenant_id.innerHTML = (o.firms || []).map((f) => '<option value="' + f.id + '">' + esc(f.name) + "</option>").join("");
        }
        return;
      }
      if (t.closest("[data-cancelform]")) { bookForm.hidden = true; return; }
      if (t.closest("[data-newroom]")) { openEdit(null); return; }
      if (t.closest("[data-closeedit]")) { editForm.hidden = true; return; }
      const card = t.closest("[data-rid]");
      const room = card && rooms.find((r) => r.id === +card.dataset.rid);
      if (room && t.closest("[data-edit]")) { openEdit(room); editForm.scrollIntoView({ behavior: "smooth", block: "nearest" }); return; }
      if (room && t.closest("[data-copy]")) {
        (navigator.clipboard ? navigator.clipboard.writeText(room.screen_url) : Promise.reject()).then(() => toast("Skærmlink kopieret. Åbn det i tablettens browser ved døren."), () => toast(room.screen_url));
        return;
      }
      let b;
      if ((b = t.closest("[data-delroom]")) && editing) {
        if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen: lokale og bookinger slettes"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Slet lokale"; }, 4000); return; }
        try { await api("DELETE", "/api/admin/rooms/" + editing.id); toast(editing.name + " er slettet"); editForm.hidden = true; load(); } catch (err) { toast(err.message, true); }
        return;
      }
      if ((b = t.closest("[data-cancelbook]"))) {
        if (!b.dataset.sure) { b.dataset.sure = "1"; b.textContent = "Tryk igen"; setTimeout(() => { delete b.dataset.sure; b.textContent = "Aflys"; }, 3000); return; }
        try { await api("DELETE", "/api/admin/bookings/" + b.closest("[data-bid]").dataset.bid); toast("Bookingen er aflyst"); loadBookings(); } catch (err) { toast(err.message, true); }
      }
    });

    $$(".rm-day").addEventListener("change", (e) => { day = e.target.value || isoDay(new Date()); loadBookings(); });
    $$(".rm-priv").addEventListener("change", (e) => o.onPrivacy(e.target.value));

    bookForm.addEventListener("submit", async (e) => {
      e.preventDefault(); const f = bookForm;
      const body = { room_id: +f.room_id.value, title: f.title.value.trim(), start: f.date.value + "T" + f.start.value, end: f.date.value + "T" + f.end.value,
        attendees: +f.attendees.value || 0 };
      body.tenant_id = isHouse ? +f.tenant_id.value : o.scope.tenant_id;
      try {
        await api("POST", "/api/admin/bookings", body);
        toast("Booket"); f.hidden = true; f.title.value = "";
        day = f.date.value; $$(".rm-day").value = day; loadBookings();
      } catch (err) { toast(err.message, true); }
    });

    editForm.addEventListener("submit", async (e) => {
      e.preventDefault(); const f = editForm;
      const body = { name: f.name.value.trim(), location: f.location.value.trim(), capacity: +f.capacity.value || 0, description: f.description.value.trim(),
        setups: list(f.setups.value), equipment: list(f.equipment.value), privacy: f.privacy.value };
      try {
        if (editing) { body.active = f.active.checked; await api("PATCH", "/api/admin/rooms/" + editing.id, body); toast("Gemt"); }
        else { const r = await api("POST", "/api/admin/rooms", Object.assign(body, o.scope)); toast(r.name + " er oprettet. Tilføj gerne et billede."); await load(); openEdit(rooms.find((x) => x.id === r.id)); return; }
        f.hidden = true; load();
      } catch (err) { toast(err.message, true); }
    });

    editForm.photo.addEventListener("change", async (e) => {
      const file = e.target.files[0]; if (!file || !editing) return;
      const fd = new FormData(); fd.append("file", file);
      try {
        const r = await api("POST", "/api/admin/rooms/" + editing.id + "/photo", fd, true);
        toast("Billedet er gemt"); editing = r; $$(".rm-photo").innerHTML = '<img src="' + esc(r.photo_url) + '" alt="">'; load();
      } catch (err) { toast(err.message, true); }
      e.target.value = "";
    });

    load();
    return { reload: load };
  }

  window.NoddRooms = { mount };
})();
