// A message arrives as ?msg=… in the address. Once it's on screen, drop it from the address so a refresh or a
// reload after a sync doesn't show a stale message again.
const url = new URL(location.href);
if (url.searchParams.has("msg")) {
  url.searchParams.delete("msg");
  history.replaceState(null, "", url.pathname + url.search + url.hash);
}

// A record card's action panels float over the list, so only one is open at a time; Escape closes it.
document.addEventListener("toggle", (ev) => {
  if (ev.target.matches?.("details.act") && ev.target.open) {
    document.querySelectorAll("details.act[open]").forEach((d) => { if (d !== ev.target) d.open = false; });
  }
}, true);
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  document.querySelectorAll("details.act[open]").forEach((d) => {
    const inside = d.contains(document.activeElement);
    d.open = false;
    if (inside) d.querySelector("summary").focus();
  });
});

// A citation like [3] points into the folded Sources list: open it so the browser can scroll to the source.
function openTarget() {
  const el = location.hash && document.getElementById(location.hash.slice(1));
  const box = el && el.closest("details");
  if (box && !box.open) { box.open = true; el.scrollIntoView({block: "center"}); }
}
window.addEventListener("hashchange", openTarget);
openTarget();

// Gained a certification uses its own date, so the usual day field steps aside and only one date is posted.
const entryKind = document.querySelector("[data-entry-kind]");
const entryDay = document.querySelector("[data-entry-day]");
const certDate = document.querySelector("[data-cert-date]");
const certDay = document.querySelector("[data-cert-day]");
if (entryKind && entryDay && certDate && certDay) {
  entryKind.addEventListener("change", () => {
    const on = entryKind.value === "certification";
    certDate.hidden = !on;
    entryDay.hidden = on;
    entryDay.disabled = on;
    certDay.disabled = !on;
    certDay.name = on ? "day" : "";
  });
}

// A preset on Ask fills the question so it can be edited before it is sent.
const askPreset = document.querySelector("[data-ask-preset]");
const askQuestion = document.querySelector("[data-ask-question]");
if (askPreset && askQuestion) {
  askPreset.addEventListener("change", () => {
    if (askPreset.value) askQuestion.value = askPreset.value;
  });
}
