(function () {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const people = q => fetch("/api/employees?q=" + encodeURIComponent(q)).then(r => r.ok ? r.json() : []);

  // Dropdowns: app switcher, notifications, account menu
  const toggles = [[$("#appsBtn"), $("#switcher")], ...$$(".topbar .menu").map(m => [$("button", m), m])];
  toggles.forEach(([btn, panel]) => btn && btn.addEventListener("click", e => {
    e.stopPropagation();
    const open = !panel.classList.contains("open");
    toggles.forEach(([b, p]) => { p.classList.remove("open"); b && b.setAttribute("aria-expanded", false); });
    panel.classList.toggle("open", open);
    btn.setAttribute("aria-expanded", open);
  }));
  toggles.forEach(([, panel]) => panel && panel.addEventListener("click", e => e.stopPropagation()));
  document.addEventListener("click", () => toggles.forEach(([b, p]) => { if (p) { p.classList.remove("open"); b && b.setAttribute("aria-expanded", false); } }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") document.body.click(); });

  // Org chart: drag a person from the side list onto a level.
  $$("[data-drag-emp]").forEach(card => card.addEventListener("dragstart", e => {
    e.dataTransfer.setData("text/plain", card.dataset.dragEmp);
    e.dataTransfer.effectAllowed = "copy";
  }));
  $$("[data-drop-node]").forEach(zone => {
    zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drop-on"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drop-on"));
    zone.addEventListener("drop", async e => {
      e.preventDefault(); zone.classList.remove("drop-on");
      const body = new URLSearchParams({ action: "add_member", node_id: zone.dataset.dropNode,
        employee_id: e.dataTransfer.getData("text/plain"), _csrf: $("meta[name=csrf-token]").content });
      await fetch(location.href, { method: "POST", body });
      location.reload();
    });
  });
  // Filter the side list
  const empFilter = $("#empFilter");
  empFilter && empFilter.addEventListener("input", () => {
    const q = empFilter.value.toLowerCase();
    $$("[data-drag-emp]").forEach(c => c.hidden = q && !c.textContent.toLowerCase().includes(q));
  });

  // Employee pickers: <input data-emp> gets live suggestions; the value is the employee ID.
  let pickerId = 0;
  function wirePicker(input) {
    if (input.dataset.wired) return;
    input.dataset.wired = 1;
    const dl = document.createElement("datalist");
    dl.id = "emp-dl-" + (++pickerId);
    input.setAttribute("list", dl.id);
    input.after(dl);
    input.addEventListener("input", debounce(async () => {
      const q = input.value.trim();
      if (q.length < 2) return;
      const list = await people(q);
      dl.innerHTML = list.map(p => `<option value="${esc(p.id)}">${esc(p.name)} — ${esc(p.designation)}, ${esc(p.department)}</option>`).join("");
    }, 200));
  }
  $$("input[data-emp]").forEach(wirePicker);

  // Repeaters: <div data-repeater> with a <template>, [data-add] and [data-remove] buttons.
  $$("[data-repeater]").forEach(rep => {
    const tpl = $("template", rep), body = $("[data-rows]", rep), max = +rep.dataset.max || 999;
    const renumber = () => $$("[data-row]", body).forEach((row, i) => $$(".rownum", row).forEach(n => n.textContent = i + 1));
    const wire = row => {
      $$("input[data-emp]", row).forEach(wirePicker);
      $$("[data-switch]", row).forEach(applySwitch);
    };
    $("[data-add]", rep)?.addEventListener("click", () => {
      if ($$("[data-row]", body).length >= max) { alert("Maximum " + max + " rows."); return; }
      const frag = tpl.content.cloneNode(true);
      const row = frag.querySelector("[data-row]");
      body.appendChild(frag);
      wire(row); renumber();
      row.querySelector("input,select")?.focus();
    });
    body.addEventListener("click", e => {
      const btn = e.target.closest("[data-remove]");
      if (!btn) return;
      const rows = $$("[data-row]", body);
      if (rows.length <= (+rep.dataset.min || 0)) return;
      btn.closest("[data-row]").remove(); renumber();
    });
    renumber();
  });

  // Show/hide parts of a row from a select: <select data-switch="scope-selector"> + [data-when="value"] in the scope.
  function applySwitch(sel) {
    const scope = sel.closest(sel.dataset.switch) || document;
    const run = () => $$("[data-when]", scope).forEach(el => {
      if (el.closest(sel.dataset.switch) !== scope && scope !== document) return;
      const show = el.dataset.when.split(",").includes(sel.value);
      el.hidden = !show;  // hide only: rows post parallel arrays, disabled fields would shift them
    });
    if (!sel.dataset.switchWired) { sel.addEventListener("change", run); sel.dataset.switchWired = 1; }
    run();
  }
  $$("[data-switch]").forEach(applySwitch);

  // Yes/no blocks: reveal the note when Yes is chosen.
  $$("[data-need]").forEach(block => {
    const run = () => { const yes = $("input[value='1']", block).checked; $$("[data-if-yes]", block).forEach(el => el.hidden = !yes); };
    $$("input[type=radio]", block).forEach(r => r.addEventListener("change", run));
    run();
  });
})();
