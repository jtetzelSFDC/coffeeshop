// Loads the real sync.js with a fake page. A finished daily job reloads once.
// A typed line, or a day box that is already filled in, does not.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function job(state) {
  return { state, message: "ok", pct: state === "done" ? 100 : 10,
    steps: [{ state, label: "Suggest", detail: "" }], started: "1:00 PM" };
}

function makeEl() {
  return {
    style: {}, className: "", textContent: "", hidden: false, dataset: {}, type: "", children: [],
    append(...xs) { this.children.push(...xs); },
    replaceChildren() { this.children = []; },
    addEventListener() {},
    querySelector() { return null; },
  };
}

function texts(n, acc = []) {
  if (n.textContent) acc.push(n.textContent);
  for (const c of n.children || []) texts(c, acc);
  return acc;
}

async function flush() {
  for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r));
}

async function run(fields) {
  const box = makeEl();
  const state = { body: { daily: job("running") } };
  const timers = [];
  let reloads = 0;
  const context = {
    document: {
      addEventListener() {},
      createElement: () => makeEl(),
      querySelector(sel) { return sel.includes('data-job="daily"') ? box : null; },
      querySelectorAll(sel) { return sel.startsWith("textarea") ? fields : []; },
    },
    location: { reload() { reloads++; } },
    fetch: async () => ({ json: async () => state.body }),
    setTimeout(fn) { timers.push(fn); return timers.length; },
  };
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/careeros/web/static/sync.js"), "utf8"),
    vm.createContext(context));
  await flush();
  assert.equal(reloads, 0);
  state.body = { daily: job("done") };
  timers.shift()();
  await flush();
  return { reloads, shown: texts(box) };
}

(async () => {
  const clean = await run([]);
  assert.equal(clean.reloads, 1, "an empty page should reload once");

  const typed = await run([{ type: "textarea", value: "a note I have not saved" }]);
  assert.equal(typed.reloads, 0, "typed text must stay");
  assert.ok(typed.shown.includes("Show the new items"), "the button is how you load the new three");

  const day = await run([{ type: "date", value: "2026-11-06" }]);
  assert.equal(day.reloads, 1, "the day box is already filled in");
})().catch((err) => { console.error(err); process.exit(1); });
