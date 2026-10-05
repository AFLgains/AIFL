// The Jobs drawer: everything the app has started (matches, tournaments, renders, checks, ratings), with live logs.
// Any section starts one with startJob(kind, params); the drawer opens on it and follows it until it ends.
import { get, post } from "./api.js";
import { h, clear, toast, when } from "./ui.js";

const drawer = () => document.getElementById("jobs");
let open = new Set();          // job ids whose log is expanded
let timer = null;
const listeners = [];

export function onJobDone(fn) { listeners.push(fn); }

export async function startJob(kind, params) {
  try {
    const job = await post("/api/jobs", { kind, params });
    toast(`Started: ${job.title}`);
    open.add(job.id);
    showDrawer(true);
    refresh();
    return job;
  } catch (e) { toast(e.message, "bad"); throw e; }
}

export function showDrawer(on) {
  drawer().classList.toggle("hidden", !on);
  if (on) refresh();
}

const seen = {};
async function refresh() {
  let jobs;
  try { jobs = await get("/api/jobs?limit=25"); } catch { return; }
  const running = jobs.filter((j) => j.status === "running").length;
  const badge = document.getElementById("jobs-badge");
  badge.textContent = running; badge.classList.toggle("hidden", !running);
  for (const j of jobs) {                                     // tell the page when something it may be showing finished
    if (seen[j.id] === "running" && j.status !== "running") {
      listeners.forEach((f) => f(j));
      toast(`${j.status}: ${j.title}`, j.status === "done" ? "ok" : "bad", j.status === "done" ? nextStep(j) : null);
    }
    seen[j.id] = j.status;
  }
  if (!drawer().classList.contains("hidden")) await render(jobs);
  clearTimeout(timer);
  timer = setTimeout(refresh, running ? 2000 : 8000);
}

// Where a finished job's result lives: its video, else its match, else its tournament's games.
function nextStep(j) {
  const out = j.outputs || {};
  if (out.videos && out.videos.length) return { href: "#/inspect/video/" + encodeURIComponent(out.videos[0]), text: "▶ Watch video" };
  if (j.kind === "tournament") return { href: "#/play/tournament", text: "See standings" };
  if (out.matches && out.matches.length === 1) return { href: "#/inspect/match/" + out.matches[0], text: "Open match #" + out.matches[0] };
  if (out.matches && out.matches.length > 1) return { href: "#/inspect/results", text: `See the ${out.matches.length} games` };
  return null;
}

function outputsRow(out) {
  const bits = [];
  for (const v of out.videos || []) bits.push(h("a.btn.small", { href: "#/inspect/video/" + encodeURIComponent(v) }, "▶ Watch " + v.split("/").pop()));
  if (out.matches && out.matches.length)
    bits.push(h("span.muted", "matches:"), out.matches.slice(0, 30).map((m) => h("a", { href: `#/inspect/match/${m}` }, "#" + m)), out.matches.length > 30 ? h("span.muted", "…") : null);
  return bits.length ? h("div.row", { style: { marginTop: "6px" } }, bits) : null;
}

async function render(jobs) {
  const items = [];
  for (const j of jobs) {
    const body = [];
    if (j.status !== "running" && !open.has(j.id)) body.push(outputsRow(j.outputs || {}));   // results stay one click away
    if (open.has(j.id)) {
      const full = await get(`/api/jobs/${j.id}?tail=20000`);
      body.push(outputsRow(full.outputs || {}));
      body.push(h("pre.log", full.log || "(no output yet)"));
      body.push(h("div.muted.mono", { style: { fontSize: "11px" } }, "afl.py " + j.argv.join(" ")));
    }
    items.push(h("div.job",
      h("div.row", h("span.status." + j.status, j.status), h("span.title.grow", j.title),
        j.status === "running" ? h("button.btn.small.ghost", { onclick: async () => { await post(`/api/jobs/${j.id}/cancel`); refresh(); } }, "cancel") : null,
        h("button.btn.small.ghost", { onclick: () => { open.has(j.id) ? open.delete(j.id) : open.add(j.id); refresh(); } }, open.has(j.id) ? "hide" : "log")),
      h("div.when", when(j.created) + (j.finished ? " → " + when(j.finished).slice(11) : "") + (j.uses_llm ? " · LLM" : "")),
      body));
  }
  clear(drawer(), h("div.row", h("h2", "Jobs"), h("button.btn.small.ghost.right", { onclick: () => showDrawer(false) }, "close")),
    items.length ? items : h("p.muted", "Nothing yet. Matches, tournaments, renders and checks you start appear here."));
}

export function initJobs() {
  document.getElementById("jobs-toggle").addEventListener("click", () => showDrawer(drawer().classList.contains("hidden")));
  refresh();
}
