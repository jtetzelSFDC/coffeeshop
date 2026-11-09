// Intake Review Queue buttons save in the background: the row fades out when it leaves the current view, else redraws in place.
// Without this script the same forms still work as normal page loads.
// The redraw drops text typed in other boxes. Match the action attribute, not form.action: on the page that
// property is an absolute URL, and for HTML still inside the template it is empty.
const keep = (row, fresh, saved) => {
  const take = (el) => el.name && (el.tagName !== "INPUT" || (el.type || "text") === "text");
  const action = (el) => (el.form && el.form.getAttribute("action")) || "";
  const summary = (d) => {
    const s = d.querySelector("summary");
    return (s ? s.textContent : "").trim();
  };
  const left = [...fresh.querySelectorAll("textarea, select, input")].filter(take);
  for (const el of row.querySelectorAll("textarea, select, input")) {
    if (!take(el) || saved.contains(el)) continue;
    const i = left.findIndex((n) => n.name === el.name && action(n) === action(el));
    if (i < 0) continue;
    left[i].value = el.value;
    left.splice(i, 1);
  }
  const open = [...fresh.querySelectorAll("details")];
  for (const d of row.querySelectorAll("details")) {
    if (!d.open) continue;
    const i = open.findIndex((n) => summary(n) === summary(d));
    if (i < 0) continue;
    open[i].open = true;
    open.splice(i, 1);
  }
};

document.addEventListener("submit", async (ev) => {
  const form = ev.target;
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
