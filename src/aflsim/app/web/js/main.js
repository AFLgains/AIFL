// The shell: navigation built from the server's section list, and a hash router: #/<section>/<page>/<arg...>?filters.
// Adding a section = one module in sections/ exporting render(view, route, meta, query) + one entry in SECTIONS below
// and in server.py's SECTIONS list.
import { get } from "./api.js";
import { h, clear } from "./ui.js";
import { initJobs } from "./jobs.js";
const SECTIONS = {};                                                      // loaded on demand: only the sections the server lists
const section_ = async (id) => (SECTIONS[id] ||= await import(`./sections/${id}.js`));
let meta = null;

async function route() {
  // #/<section>/<page>/<arg...>?key=value&...   (the query carries filters, so a filtered view can be linked to)
  const [path, search = ""] = (location.hash.replace(/^#\/?/, "") || "play").split("?");
  const [section, ...rest] = path.split("/");
  const query = Object.fromEntries(new URLSearchParams(search));
  for (const a of document.querySelectorAll("nav a")) a.classList.toggle("on", a.dataset.id === section);
  const view = document.getElementById("view");
  const mod = meta && meta.sections.some((s) => s.id === section) ? await section_(section) : null;
  if (!mod) { clear(view, h("p.pad", "Unknown page.")); return; }
  try {
    await mod.render(view, rest, meta, query);
  } catch (e) {
    console.error(e);
    clear(view, h("div.card", h("h2", "Something went wrong"), h("pre.log", String(e.stack || e))));
  }
}

// The top bar's switch: game and engine version. Kept in a cookie, so every request (API, videos, media) carries it;
// switching reloads the page at the section's start (match ids and bots differ between games).
function contextSwitch() {
  const sel = document.getElementById("ctx");
  clear(sel, meta.contexts.map((c) => h("option", { value: c.id, selected: c.id === meta.context }, c.label + (c.current ? "" : " (old)"))));
  sel.onchange = () => {
    document.cookie = `afl_ctx=${sel.value}; path=/; max-age=31536000; SameSite=Lax`;
    location.hash = "#/" + ((location.hash.replace(/^#\/?/, "").split(/[/?]/)[0]) || "play");
    location.reload();
  };
  document.body.dataset.game = meta.game;
  document.body.classList.toggle("old-engine", meta.engine_version !== meta.engine_latest);
}

async function start() {
  meta = await get("/api/meta");
  window.AFL_META = meta;                                                 // for deep modules (the board) that check features
  contextSwitch();
  clear(document.getElementById("nav"), meta.sections.map((s) => h("a", { href: `#/${s.id}`, title: s.blurb, "data-id": s.id }, s.title)));
  initJobs();
  window.addEventListener("hashchange", route);
  route();
}

start();
