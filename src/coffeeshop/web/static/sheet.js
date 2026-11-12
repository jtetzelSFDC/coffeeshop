// Intake Review Queue buttons save in the background: the row fades out when it leaves the current view, else redraws in place.
// Without this script the same forms still work as normal page loads.
// The bulk Looks right does the same for each row the server confirmed. Rows it skipped (Claude has not read them) stay put.
// The redraw drops text typed in other boxes. Match the action attribute, not form.action: on the page that
// property is an absolute URL, and for HTML still inside the template it is empty.
const keep = (row, fresh, saved) => {
  const take = (el) => el.name && (el.tagName !== "INPUT" || (el.type || "text") === "text");
  const action = (el) => (el.form && el.form.getAttribute("action")) || "";
  const left = [...fresh.querySelectorAll("textarea, select, input")].filter(take);
  for (const el of row.querySelectorAll("textarea, select, input")) {
    if (!take(el) || saved.contains(el)) continue;
    const i = left.findIndex((n) => n.name === el.name && action(n) === action(el));
    if (i < 0) continue;
    left[i].value = el.value;
    left.splice(i, 1);
  }
  // A save only adds or removes the win box at the end, so earlier boxes stay at the same index.
  const prev = [...row.querySelectorAll("details")];
  const next = [...fresh.querySelectorAll("details")];
  for (let i = 0; i < prev.length; i++) if (prev[i].open && next[i]) next[i].open = true;
  const ticks = (root) => [...root.querySelectorAll("input")].filter((el) => el.type === "checkbox" && el.name === "id");
  const oldTicks = ticks(row);
  const newTicks = ticks(fresh);
  for (let i = 0; i < oldTicks.length; i++) if (newTicks[i]) newTicks[i].checked = !!oldTicks[i].checked;
};

const sheetBoxes = () => [...document.querySelectorAll("table.sheet input[name=id]")];

const selectedCount = () => {
  const list = sheetBoxes().filter((b) => {
    const row = b.closest("tr");
    return !row || !row.classList.contains("gone");
  });
  const n = list.filter((b) => b.checked).length;
  const sel = document.getElementById("seln");
  if (sel) sel.textContent = String(n);
  const all = document.getElementById("sheet-all");
  if (all) all.checked = list.length > 0 && n === list.length;
};

document.addEventListener("change", (ev) => {
  const t = ev.target;
  if (!t || t.tagName !== "INPUT") return;
  if (t.id === "sheet-all") for (const box of sheetBoxes()) box.checked = t.checked;
  if (t.id === "sheet-all" || t.name === "id") selectedCount();
});

document.addEventListener("submit", async (ev) => {
  const form = ev.target;
  if (form.getAttribute("action") === "/sheet/ok") {
    ev.preventDefault();
    for (const box of sheetBoxes()) if (box.checked) {
      const row = box.closest("tr");
      if (row) row.classList.add("busy");
    }
    let resp;
    try {
      resp = await fetch(form.action, { method: "POST", body: new FormData(form), headers: { "X-Sheet": "1" }, credentials: "same-origin" });
    } catch (e) {
      location.reload();
      return;
    }
    if (!resp.ok) {
      location.reload();
      return;
    }
    let body;
    try {
      body = await resp.json();
    } catch (e) {
      location.reload();
      return;
    }
    const gone = new Set((body.gone || []).map(String));
    let n = 0;
    for (const id of gone) {
      const row = document.getElementById("r" + id);
      if (!row) continue;
      row.classList.add("gone");
      const box = row.querySelector("input[name=id]");
      if (box) box.checked = false;
      n += 1;
      setTimeout(() => row.remove(), 400);
    }
    const count = document.getElementById("rowcount");
    if (count && n) count.textContent = String(Math.max(0, parseInt(count.textContent, 10) - n));
    for (const [id, html] of Object.entries(body.rows || {})) {
      const row = document.getElementById("r" + id);
      if (!row) continue;
      const tpl = document.createElement("template");
      tpl.innerHTML = String(html).trim();
      const fresh = tpl.content.querySelector("tr");
      if (!fresh) continue;
      keep(row, fresh, form);
      row.replaceWith(fresh);
    }
    selectedCount();
    return;
  }
  const row = form.closest("table.sheet tr[id^='r']");
  if (!row) return;
  ev.preventDefault();
  const data = new FormData(form);
  if (ev.submitter && ev.submitter.name) data.append(ev.submitter.name, ev.submitter.value);
  row.classList.add("busy");
  let resp;
  try {
    resp = await fetch(form.action, { method: "POST", body: data, headers: { "X-Sheet": "1" }, credentials: "same-origin" });
  } catch (e) {
    location.reload();
    return;
  }
  if (!resp.ok) {
    location.reload();
    return;
  }
  if (resp.headers.get("X-Row") === "gone") {
    row.classList.add("gone");
    const count = document.getElementById("rowcount");
    if (count) count.textContent = Math.max(0, parseInt(count.textContent, 10) - 1);
    setTimeout(() => row.remove(), 400);
    return;
  }
  const tpl = document.createElement("template");
  tpl.innerHTML = (await resp.text()).trim();
  const fresh = tpl.content.querySelector("tr");
  if (!fresh) {
    location.reload();
    return;
  }
  keep(row, fresh, form);
  row.replaceWith(fresh);
});
