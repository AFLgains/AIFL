// Small DOM helpers shared by every section. h("div.card#x", {onclick}, child, ...) builds elements.
import { get } from "./api.js";

export function h(tag, attrs, ...children) {
  const [name, ...parts] = tag.split(/(?=[.#])/);
  const el = document.createElement(name || "div");
  for (const p of parts) p[0] === "." ? el.classList.add(p.slice(1)) : (el.id = p.slice(1));
  // a first argument that isn't a plain attributes object (text, a number, even 0, a node, a list) is a child
  if (attrs !== undefined && attrs !== null && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { children.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k in el && k !== "list") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  // children may be nested lists to any depth (a group header followed by a list of items, inside a list of groups)
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

export const clear = (el, ...children) => {
  el.replaceChildren();
  el.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false).map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
  return el;
};

// A notice in the corner. `link` = {href, text} adds a button that goes there (e.g. "Watch video" when a job finishes).
export function toast(msg, kind = "", link = null) {
  const t = h("div.toast" + (kind ? "." + kind : ""), h("div", msg),
    link ? h("a.btn.small", { href: link.href, style: { marginTop: "6px", display: "inline-block" }, onclick: () => t.remove() }, link.text) : null);
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), link ? 15000 : kind === "bad" ? 9000 : 4500);
}

export function field(label, input) { return h("div.field", h("label", label), input); }
export function check(label, input) { return h("label.check", input, label); }

export function table(columns, rows, onRow) {
  // columns: [{key, label, num?, fmt?}]
  const head = h("tr", columns.map((c) => h("th" + (c.num ? ".num" : ""), c.label)));
  const body = rows.map((r) => h("tr" + (onRow ? ".click" : ""), { onclick: onRow ? () => onRow(r) : null },
    columns.map((c) => h("td" + (c.num ? ".num" : ""), c.fmt ? c.fmt(r[c.key], r) : r[c.key] ?? ""))));
  return h("table", h("thead", head), h("tbody", body));
}

export const when = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) : "");
export const short = (spec) => (spec || "").replace(/^ladder\//, "").replace(/^search(\[[^\]]*\])?:/, "🔍 ").replace(/^zoo:/, "zoo:");

// ---- the bot library, fetched once per page load (reloaded after a bot is saved)
let botsPromise = null;
export function bots(reload = false) {
  if (reload || !botsPromise) botsPromise = get("/api/develop/bots");
  return botsPromise;
}

const GROUP_ORDER = ["zoo", "ladder", "community", "drafts", "analyst", "evolved", "llm"];
export function grouped(list) {
  const g = {};
  for (const b of list) (g[b.group] ||= []).push(b);
  return Object.entries(g).sort(([a], [b]) => (GROUP_ORDER.indexOf(a) + 99) % 99 - (GROUP_ORDER.indexOf(b) + 99) % 99);
}

const GROUP_TITLES = { zoo: "Zoo (built-in)", ladder: "Ladder (evolved and hand-written)", community: "Community", drafts: "Drafts",
  analyst: "Written by analysts", evolved: "Evolved champions", llm: "LLM / instruction bots (cost money)" };
const rating = (b) => (b.rating_240 ? `${b.rating_240}` : b.rating_120 ? `${b.rating_120} @120s` : "");

// A bot picker: a real dropdown of the whole library, grouped by kind with ratings, a filter box that narrows it,
// "other…" for any file path, and an optional look-ahead toggle (which wraps the choice as search:<bot>).
export async function botPicker(labelText, initial = "", { lookahead = true, blank = false } = {}) {
  const list = await bots();
  const sel = h("select", { style: { minWidth: "320px", maxWidth: "420px" } });
  const filter = h("input", { placeholder: "filter…", style: { width: "110px" } });
  const other = h("input.hidden", { placeholder: "path to a .py bot, or any spec", style: { minWidth: "300px" } });
  const la = h("input", { type: "checkbox" });
  let chosen = initial;
  function fill() {
    const f = filter.value.trim().toLowerCase();
    const shown = list.filter((b) => !f || b.spec.toLowerCase().includes(f));
    clear(sel,
      blank ? h("option", { value: "" }, "— pick a bot —") : null,
      grouped(shown).map(([g, items]) => h("optgroup", { label: GROUP_TITLES[g] || g },
        items.map((b) => h("option", { value: b.spec }, b.spec.replace(/^ladder\//, "") + (rating(b) ? "   · " + rating(b) : ""))))),
      h("option", { value: "__other__" }, "other… (type a spec)"));
    if (list.some((b) => b.spec === chosen) && shown.some((b) => b.spec === chosen)) sel.value = chosen;
    else if (chosen && !list.some((b) => b.spec === chosen)) { sel.value = "__other__"; other.value = chosen; }
    other.classList.toggle("hidden", sel.value !== "__other__");
  }
  sel.addEventListener("change", () => { if (sel.value !== "__other__") chosen = sel.value; other.classList.toggle("hidden", sel.value !== "__other__"); });
  filter.addEventListener("input", fill);
  fill();
  const wrap = h("div.field", h("label", labelText), h("div.row", sel, filter, (lookahead && (!window.AFL_META || window.AFL_META.features.value_model)) ? check("look-ahead", la) : null), other);
  wrap.value = () => {
    const s = (sel.value === "__other__" ? other.value : sel.value).trim();
    return la.checked && s && !s.startsWith("search") ? "search:" + s : s;
  };
  wrap.set = (v) => { chosen = v; filter.value = ""; fill(); };
  wrap.onchange = (fn) => sel.addEventListener("change", fn);
  return wrap;
}
