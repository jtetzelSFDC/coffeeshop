// Loads the real sheet.js with a fake row. A button on one form redraws the row from the server.
// Text, dropdowns, and open details that were not in that form stay. The form that saved shows the server's values.
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const VOID = new Set(["input"]);

function attrs(s) {
  const out = {};
  const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+)))?/g;
  let m;
  while ((m = re.exec(s))) out[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? "";
  return out;
}

function textOf(node) {
  if (!node.tagName) return node.data || "";
  return (node.childNodes || []).map(textOf).join("");
}

function linkParents(el) {
  for (const n of el.childNodes || []) {
    if (!n.tagName) continue;
    n.parentElement = el;
    linkParents(n);
  }
}

function matchSimple(el, sel) {
  const m = sel.match(/^([a-z0-9]+)(?:\.([a-z0-9_-]+))?(\[[^\]]+\])?$/i);
  if (!m || m[1].toLowerCase() !== el.tagName.toLowerCase()) return false;
  if (m[2] && !(el.className || "").split(/\s+/).includes(m[2])) return false;
  if (!m[3]) return true;
  const pm = m[3].slice(1, -1).match(/^([a-z]+)\^=['"]?([^'"]+)['"]?$/i);
  return !!pm && (el.getAttribute(pm[1]) || "").startsWith(pm[2]);
}

function matches(el, sel) {
  const parts = sel.trim().split(/\s+/);
  const last = parts.pop();
  if (!matchSimple(el, last)) return false;
  if (!parts.length) return true;
  const rest = parts.join(" ");
  let p = el.parentElement;
  while (p) {
    if (p.tagName && matches(p, rest)) return true;
    p = p.parentElement;
  }
  return false;
}

function queryAll(root, sel) {
  const alts = sel.split(",").map((s) => s.trim());
  const out = [];
  function walk(node) {
    for (const child of node.childNodes || []) {
      if (!child.tagName) continue;
      if (alts.some((a) => matches(child, a))) out.push(child);
      walk(child);
    }
  }
  walk(root);
  return out;
}

function makeEl(tag, attributes, inTemplate) {
  const el = {
    tagName: tag, childNodes: [], parentElement: null, inTemplate: !!inTemplate,
    attributes: { ...attributes }, className: attributes.class || "",
  };
  el.classList = { add(c) {
    const parts = el.className.split(/\s+/).filter(Boolean);
    if (!parts.includes(c)) parts.push(c);
    el.className = parts.join(" ");
  } };
  el.getAttribute = (k) => (k.toLowerCase() in el.attributes ? el.attributes[k.toLowerCase()] : null);
  el.querySelector = (sel) => queryAll(el, sel)[0] || null;
  el.querySelectorAll = (sel) => queryAll(el, sel);
  el.closest = (sel) => {
    let n = el;
    while (n) {
      if (n.tagName && matches(n, sel)) return n;
      n = n.parentElement;
    }
    return null;
  };
  el.contains = (node) => {
    let n = node;
    while (n) {
      if (n === el) return true;
      n = n.parentElement;
    }
    return false;
  };
  el.replaceWith = (node) => {
    const p = el.parentElement;
    if (!p) return;
    const i = p.childNodes.indexOf(el);
    p.childNodes.splice(i, 1, node);
    node.parentElement = p;
    el.parentElement = null;
  };
  Object.defineProperty(el, "textContent", { get() { return textOf(el); } });
  Object.defineProperty(el, "name", { get() { return el.getAttribute("name") || ""; } });
  Object.defineProperty(el, "form", { get() {
    let n = el.parentElement;
    while (n) {
      if (n.tagName === "FORM") return n;
      n = n.parentElement;
    }
    return null;
  } });
  Object.defineProperty(el, "type", { get() {
    if (tag === "SELECT") return "select-one";
    if (tag === "TEXTAREA") return "textarea";
    if (tag === "INPUT") return (el.getAttribute("type") || "text").toLowerCase();
    return "";
  } });
  if (tag === "FORM") {
    // On the page, form.action is an absolute URL. A form still inside a template reports "".
    Object.defineProperty(el, "action", { get() {
      return el.inTemplate ? "" : "http://127.0.0.1:8765" + (el.getAttribute("action") || "");
    } });
  }
  if (tag === "INPUT") {
    let value = attributes.value ?? "";
    Object.defineProperty(el, "value", { get() { return value; }, set(v) { value = String(v); } });
  }
  if (tag === "TEXTAREA") {
    let value = null;
    Object.defineProperty(el, "value", {
      get() { return value === null ? textOf(el) : value; },
      set(v) { value = String(v); },
    });
  }
  if (tag === "SELECT") {
    Object.defineProperty(el, "value", {
      get() {
        const opts = el.querySelectorAll("option");
        const chosen = opts.find((o) => o.selected) || opts[0];
        return chosen ? (chosen.getAttribute("value") ?? "") : "";
      },
      set(v) {
        for (const o of el.querySelectorAll("option")) o.selected = (o.getAttribute("value") ?? "") === String(v);
      },
    });
  }
  if (tag === "OPTION") el.selected = "selected" in attributes;
  if (tag === "DETAILS") el.open = "open" in attributes;
  return el;
}

function parseNodes(html, start, stopTag, inTemplate) {
  const nodes = [];
  let i = start;
  while (i < html.length) {
    if (html.startsWith("</", i)) {
      const m = html.slice(i).match(/^<\/\s*([a-zA-Z0-9]+)\s*>/);
      if (!m) { i += 1; continue; }
      if (stopTag && m[1].toLowerCase() === stopTag) return [nodes, i + m[0].length];
      i += m[0].length;
      continue;
    }
    if (html[i] !== "<") {
      const j = html.indexOf("<", i);
      const end = j < 0 ? html.length : j;
      nodes.push({ data: html.slice(i, end) });
      i = end;
      continue;
    }
    const m = html.slice(i).match(/^<([a-zA-Z0-9]+)([^>]*?)(\/?)>/);
    if (!m) { i += 1; continue; }
    const tag = m[1].toLowerCase();
    const el = makeEl(tag.toUpperCase(), attrs(m[2]), inTemplate);
    i += m[0].length;
    if (m[3] === "/" || VOID.has(tag)) { nodes.push(el); continue; }
    const [kids, next] = parseNodes(html, i, tag, inTemplate);
    el.childNodes = kids;
    linkParents(el);
    nodes.push(el);
    i = next;
  }
  return [nodes, i];
}

function createElement(tag) {
  const el = makeEl(tag.toUpperCase(), {}, false);
  if (tag.toLowerCase() !== "template") return el;
  el.content = {
    childNodes: [],
    querySelector(sel) { return queryAll(this, sel)[0] || null; },
    querySelectorAll(sel) { return queryAll(this, sel); },
  };
  Object.defineProperty(el, "innerHTML", { set(html) {
    const [nodes] = parseNodes(String(html), 0, null, true);
    el.content.childNodes = nodes;
    for (const n of nodes) {
      if (!n.tagName) continue;
      n.parentElement = null;
      linkParents(n);
    }
  } });
  return el;
}

function mount(html) {
  const [nodes] = parseNodes(html, 0, null, false);
  const table = nodes.find((n) => n.tagName === "TABLE");
  linkParents(table);
  return table;
}

// The server row puts the win box first, so a match by name alone lands on the wrong title.
function row(o) {
  const group = `<details${o.groupOpen ? " open" : ""}><summary>Group with…</summary><form method="post" action="/sheet/4/group"><input type="hidden" name="csrf" value="${o.csrf}"><select name="item"><option value="">Pick</option><option value="9"${o.item === "9" ? " selected" : ""}>Pine</option></select><input name="title" value="${o.title}"><textarea name="blurb">${o.blurb}</textarea><button>Group</button></form></details>`;
  const notes = `<details${o.notesOpen ? " open" : ""}><summary>Notes</summary></details>`;
  const winBox = `<details${o.winOpen ? " open" : ""}><summary>${o.winLabel || "Shipped it"}</summary></details>`;
  const win = `<form method="post" action="/sheet/4/win"><input name="title" value="${o.winTitle}"></form>`;
  const kind = `<form method="post" action="/sheet/4/kind"><input type="hidden" name="csrf" value="${o.csrf}"><button name="kind" value="ship">Ship</button><span class="mark">${o.mark}</span></form>`;
  const activity = `<form method="post" action="/sheet/4/activity"><select name="activity"><option value="">Nothing</option><option value="ship"${o.activity === "ship" ? " selected" : ""}>Ship</option><option value="mentor"${o.activity === "mentor" ? " selected" : ""}>Mentor</option></select><button>Set</button></form>`;
  const bits = [kind, activity, group + notes + winBox];
  if (o.winFirst) bits.splice(1, 0, win);
  else bits.push(win);
  return `<tr id="r4"><td>${bits.join("")}</td></tr>`;
}

function val(root, action, name) {
  const form = root.querySelectorAll("form").find((f) => f.getAttribute("action") === action);
  return form.querySelectorAll("input, textarea, select").find((n) => n.name === name).value;
}

function isOpen(root, label) {
  return root.querySelectorAll("details").find((n) => (n.querySelector("summary").textContent || "").trim() === label).open;
}

async function save(client, server, action, submitter) {
  const listeners = [];
  const document = {
    addEventListener(type, fn) { if (type === "submit") listeners.push(fn); },
    createElement,
    getElementById() { return null; },
  };
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/coffeeshop/web/static/sheet.js"), "utf8"), vm.createContext({
    document,
    location: { reload() { throw new Error("reloaded"); } },
    fetch: async () => ({ ok: true, headers: { get: () => null }, text: async () => server }),
    FormData: function FormData() { this.append = () => {}; },
    setTimeout() {},
  }));
  const table = mount(`<table class="sheet">${client}</table>`);
  const form = table.querySelectorAll("form").find((f) => f.getAttribute("action") === action);
  await listeners[0]({ target: form, submitter: submitter || null, preventDefault() {} });
  return table;
}

(async () => {
  const typed = {
    mark: "old", csrf: "tok", activity: "mentor", item: "9", title: "Pine 5.1.2", blurb: "typed blurb",
    winTitle: "Other win", groupOpen: true, notesOpen: false, winFirst: false,
  };
  const fromServer = {
    mark: "saved", csrf: "srv", activity: "ship", item: "", title: "G-server", blurb: "server blurb",
    winTitle: "W-server", groupOpen: false, notesOpen: false, winFirst: true,
  };
  const kind = await save(row(typed), row(fromServer), "/sheet/4/kind", { name: "kind", value: "ship" });
  assert.equal(kind.querySelectorAll("span.mark")[0].textContent, "saved", "the row should redraw");
  assert.equal(kind.querySelectorAll("tr")[0].className, "", "the saved row should not stay faded");
  assert.equal(val(kind, "/sheet/4/group", "title"), "Pine 5.1.2", "new piece of work stays");
  assert.equal(val(kind, "/sheet/4/group", "blurb"), "typed blurb", "a textarea in another form stays");
  assert.equal(val(kind, "/sheet/4/group", "item"), "9", "the nearby-work dropdown stays");
  assert.equal(val(kind, "/sheet/4/win", "title"), "Other win", "same name in another form stays put");
  assert.equal(val(kind, "/sheet/4/activity", "activity"), "mentor", "an unsaved counts-as choice stays");
  assert.equal(val(kind, "/sheet/4/group", "csrf"), "srv", "hidden fields show the server's values");
  assert.equal(isOpen(kind, "Group with…"), true, "Group with stays open");
  assert.equal(isOpen(kind, "Notes"), false, "a closed details stays closed");

  const activity = await save(row(typed), row(fromServer), "/sheet/4/activity", null);
  assert.equal(val(activity, "/sheet/4/activity", "activity"), "ship", "the form that saved shows the server's choice");
  assert.equal(val(activity, "/sheet/4/group", "title"), "Pine 5.1.2", "typing stays when counts-as saves");
  assert.equal(isOpen(activity, "Group with…"), true);

  const grouping = {
    ...typed, groupOpen: false, notesOpen: true,
  };
  const grouped = {
    ...fromServer, title: "saved title", blurb: "from server", winFirst: false,
  };
  const group = await save(row(grouping), row(grouped), "/sheet/4/group", null);
  assert.equal(val(group, "/sheet/4/group", "title"), "saved title", "Group shows the server's title");
  assert.equal(val(group, "/sheet/4/group", "blurb"), "from server");
  assert.equal(val(group, "/sheet/4/group", "item"), "", "the submitted dropdown shows the server's choice");
  assert.equal(val(group, "/sheet/4/activity", "activity"), "mentor", "a different form's dropdown stays");
  assert.equal(val(group, "/sheet/4/win", "title"), "Other win");
  assert.equal(isOpen(group, "Group with…"), false, "a closed Group with stays closed");
  assert.equal(isOpen(group, "Notes"), true, "Notes stays open");

  // A win headed "Notes" sits after the notes box. Position keeps the win open; a heading match would open the notes box.
  const clash = await save(
    row({ ...typed, groupOpen: false, notesOpen: false, winOpen: true, winLabel: "Notes" }),
    row({ ...fromServer, winOpen: false, winLabel: "Notes" }),
    "/sheet/4/kind", { name: "kind", value: "ship" });
  assert.deepEqual(clash.querySelectorAll("details").map((d) => d.open), [false, false, true],
    "the win box stays open when its heading matches Notes");
})().catch((err) => { console.error(err); process.exit(1); });
