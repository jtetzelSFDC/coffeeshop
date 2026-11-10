// Loads the real sync.js with a fake page. A finished daily job reloads once,
// and Today's three is open on the next load only. A typed line, or a day box
// that is already filled in, does not reload by itself. A failed job opens its tile.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function job(state, message) {
  return { state, message: message || "ok", pct: state === "done" ? 100 : 10,
    steps: [{ state, label: "Suggest", detail: "" }], started: "1:00 PM" };
}

function makeEl(tag) {
  const n = {
    tagName: (tag || "div").toUpperCase(),
    style: {}, className: "", textContent: "", hidden: false, dataset: {}, type: "",
    children: [], open: false, parentElement: null, listeners: [],
    append(...xs) {
      for (const x of xs) {
        if (x && typeof x === "object") x.parentElement = n;
        n.children.push(x);
      }
    },
    replaceChildren(...xs) { n.children = []; if (xs.length) n.append(...xs); },
    addEventListener(_type, fn) { n.listeners.push(fn); },
    querySelector() { return null; },
    closest(sel) {
      const home = (el) => !!el && String(el.className || "").split(/\s+/).includes("home-tile");
      for (let p = n; p; p = p.parentElement) {
        if (sel === ".home-tile > details" && p.tagName === "DETAILS" && home(p.parentElement)) return p;
      }
      return null;
    },
  };
  return n;
}

function texts(n, acc = []) {
  if (n.textContent) acc.push(n.textContent);
  for (const c of n.children || []) if (c && typeof c === "object") texts(c, acc);
  return acc;
}

function find(n, pred) {
  if (pred(n)) return n;
  for (const c of n.children || []) {
    if (c && typeof c === "object") {
      const hit = find(c, pred);
      if (hit) return hit;
    }
  }
  return null;
}

async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
}

function memory() {
  const data = {};
  return {
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
  };
}

function load(context) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/careeros/web/static/sync.js"), "utf8"),
    vm.createContext(context));
}

function boot({ fields = [], status = {}, name = "daily", store = memory(), fetch = null } = {}) {
  const box = makeEl("div");
  box.hidden = true;
  const details = makeEl("details");
  details.append(box);
  const section = makeEl("section");
  section.className = "card home-tile";
  section.append(details);
  const state = { body: status };
  const timers = [];
  let reloads = 0;
  let onSubmit = null;
  const context = {
    document: {
      addEventListener(type, fn) { if (type === "submit") onSubmit = fn; },
      createElement: (tag) => makeEl(tag),
      querySelector(sel) { return sel.includes(`data-job="${name}"`) ? box : null; },
      querySelectorAll(sel) { return sel.startsWith("textarea") ? fields : []; },
    },
    location: { reload() { reloads++; } },
    FormData: function FormData() {},
    fetch: fetch || (async () => ({ json: async () => state.body })),
    setTimeout(fn) { timers.push(fn); return timers.length; },
    sessionStorage: store,
  };
  load(context);
  return {
    box, details, state, timers, store,
    get reloads() { return reloads; },
    submit: onSubmit,
    clickShow() {
      const btn = find(box, (el) => el.tagName === "BUTTON" && el.textContent === "Show the new items");
      assert.ok(btn, "Show the new items");
      btn.listeners[0]();
    },
  };
}

async function run(fields) {
  const page = boot({ fields, status: { daily: job("running") } });
  await flush();
  assert.equal(page.reloads, 0);
  page.state.body = { daily: job("done") };
  page.timers.shift()();
  await flush();
  return page;
}

async function fresh(store) {
  const page = boot({ store, status: {} });
  await flush();
  return page;
}

(async () => {
  const clean = await run([]);
  assert.equal(clean.reloads, 1, "an empty page should reload once");
  assert.equal(clean.store.getItem("open-daily"), "1");
  const opened = await fresh(clean.store);
  assert.equal(opened.details.open, true, "Today's three opens after the new three load");
  assert.equal(opened.reloads, 0);
  const later = await fresh(clean.store);
  assert.equal(later.details.open, false, "the flag is only for that reload");

  const typed = await run([{ type: "textarea", value: "a note I have not saved" }]);
  assert.equal(typed.reloads, 0, "typed text must stay");
  assert.ok(texts(typed.box).includes("Show the new items"), "the button is how you load the new three");
  typed.clickShow();
  assert.equal(typed.reloads, 1, "the button loads the new three");
  const typedOpen = await fresh(typed.store);
  assert.equal(typedOpen.details.open, true, "Today's three opens after that reload too");
  assert.equal(typed.store.getItem("open-daily"), null);

  const day = await run([{ type: "date", value: "2026-11-06" }]);
  assert.equal(day.reloads, 1, "the day box is already filled in");

  for (const state of ["error", "partial"]) {
    const page = boot({ status: { google: job("running") }, name: "google" });
    await flush();
    assert.equal(page.details.open, true, "progress opens the tile");
    page.details.open = false;
    page.timers.shift()();
    await flush();
    assert.equal(page.details.open, false, "a later poll leaves a closed tile closed");
    page.state.body = { google: job(state, "The sync stopped early.") };
    page.timers.shift()();
    await flush();
    assert.equal(page.details.open, true, `${state} opens a closed tile`);
    assert.ok(texts(page.box).includes("The sync stopped early."));
    assert.equal(page.reloads, 0);
    assert.equal(page.store.getItem("open-daily"), null);
    page.clickShow();
    assert.equal(page.reloads, 1);
    assert.equal(page.store.getItem("open-daily"), null, "other syncs do not arm Today's three");
  }

  const button = makeEl("button");
  button.textContent = "New three";
  const form = makeEl("form");
  form.dataset.sync = "daily";
  form.action = "/daily/suggest";
  form.querySelector = () => button;
  const failed = boot({
    status: {},
    fetch: async (url) => (url === "/sync/status"
      ? { ok: true, json: async () => ({}) }
      : { ok: false, json: async () => ({ message: "Claude could not suggest three." }) }),
  });
  await flush();
  assert.equal(failed.details.open, false);
  await failed.submit({ target: form, preventDefault() {} });
  assert.equal(failed.details.open, true, "a failed start opens the tile");
  assert.ok(texts(failed.box).includes("Claude could not suggest three."));
  assert.equal(failed.box.hidden, false);
  assert.equal(failed.reloads, 0);
})().catch((err) => { console.error(err); process.exit(1); });
