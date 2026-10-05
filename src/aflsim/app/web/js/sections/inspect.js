// INSPECT: stored results (filtered, and saying exactly what is shown), one match in detail (stats, events, videos),
// one video, and the video library. Future analysis tools (possession chains, heat maps, the value over a game...)
// get a tab here.
import { get, qs } from "../api.js";
import { h, clear, table, when, short, toast } from "../ui.js";
import { startJob, onJobDone } from "../jobs.js";
import { openMatch } from "../analysis/snes.js";
const renderAnalysis = async (...a) => (await import("../analysis/page.js")).renderAnalysis(...a);      // the analysis board
const renderSetup = async (...a) => (await import("../analysis/setup_page.js")).renderSetup(...a);     // (private: not in every copy)

const TABS = [["results", "Results"], ["videos", "Video library"], ["board", "Board setup"]];   // Board setup: games with a value model
const PAGE = 200;
let current = null;                                   // the match page on screen (so a finished render refreshes it)
onJobDone((j) => { if (current && j.kind === "render" && location.hash.startsWith("#/inspect/match/")) window.dispatchEvent(new HashChangeEvent("hashchange")); });

export async function render(view, route, meta, query = {}) {
  const [page = "results", ...arg] = route;
  const body = h("div");
  const tab = page === "match" || page === "analyse" ? "results" : page === "video" ? "videos" : page;
  current = null;
  if ((page === "analyse" || page === "board") && !meta.features.analysis) {
    clear(view, h("div.card", h("p", "The analysis board isn't part of this copy of the platform. Use 👾 Watch on a match to replay it."))); return;
  }
  if (page === "analyse" || page === "board") {        // the board needs the whole screen: no section header
    clear(view, body);
    return page === "board" ? renderSetup(body) : renderAnalysis(body, Number(arg[0]));
  }
  clear(view, h("h1", "Inspect"), h("div.muted", "Every stored game: scores, statistics, events, and video."),
    h("div.tabs", TABS.filter(([id]) => id !== "board" || meta.features.board_setup).map(([id, t]) => h("a" + (id === tab ? ".on" : ""), { href: "#/inspect/" + id }, t))), body);
  if (page === "results") return results(body, query);
  if (page === "match") return match(body, Number(arg[0]));
  if (page === "video") return oneVideo(body, decodeURIComponent(arg.join("/")));
  if (page === "analyse") return renderAnalysis(body, Number(arg[0]));
  if (page === "videos") return videos(body);
}

// ---------------------------------------------------------------- results
export const resultsLink = (q) => "#/inspect/results?" + qs(q);

async function results(el, q) {
  const f = await get("/api/inspect/filters");
  const scope = h("select", Object.entries(f.scopes).map(([k, v]) => h("option", { value: k }, v)));
  const tour = h("select", h("option", { value: "" }, "— any tournament —"),
    f.tournaments.map((t) => h("option", { value: t.id }, `${t.name}  (${t.games} games${t.status === "running" ? ", running" : ""})`)));
  const bot = h("select", h("option", { value: "" }, "— any bot —"), f.bots.map((b) => h("option", { value: b.bot }, `${b.bot}  (${b.games})`)));
  const len = h("select", h("option", { value: "" }, "— any length —"), f.lengths.map((s) => h("option", { value: s }, s + " s")));
  const vid = h("input", { type: "checkbox" });
  scope.value = q.scope || "all"; tour.value = q.tournament || ""; bot.value = q.bot || ""; len.value = q.seconds || ""; vid.checked = q.has_video === "1";
  scope.disabled = !!tour.value;
  const go = () => {                                   // every filter lives in the address, so a view can be linked to
    location.hash = resultsLink({ scope: tour.value ? "" : scope.value === "all" ? "" : scope.value, tournament: tour.value, bot: bot.value, seconds: len.value, has_video: vid.checked ? "1" : "" });
  };
  for (const s of [scope, tour, bot, len, vid]) s.addEventListener("change", go);
  const out = h("div");
  const header = h("div.row");
  let offset = 0;
  const load = async (more = false) => {
    const r = await get("/api/inspect/matches?" + qs({ scope: tour.value ? "tournament" : scope.value, tournament: tour.value, bot: bot.value,
      seconds: len.value, has_video: vid.checked, limit: PAGE, offset }));
    clear(header, h("div", h("b", `${r.total} game${r.total === 1 ? "" : "s"}`), h("span.muted", " — " + r.describe)),
      tour.value ? h("a.btn.small.ghost", { href: "#/play/tournament/" + tour.value }, "standings of this tournament") : null,
      (tour.value || bot.value || len.value || vid.checked || scope.value !== "all") ? h("a.right", { href: "#/inspect/results" }, "clear filters ×") : null);
    const rows = r.rows.map((x) => h("tr.click", { onclick: () => { location.hash = "#/inspect/match/" + x.id; } },
      h("td.num", x.id), h("td", when(x.created)),
      h("td", h("span.teamA", short(x.bot_a))), h("td.num", h("b", `${x.score_a ?? "?"} – ${x.score_b ?? "?"}`)), h("td", h("span.teamB", short(x.bot_b))),
      h("td.num", x.seconds + " s"),
      h("td", x.tournament ? h("a", { href: resultsLink({ tournament: x.tournament_id }), onclick: (e) => e.stopPropagation() }, x.tournament)
        : (x.source || "").startsWith("legacy") ? h("span.muted", x.source.replace("legacy:", "history: ")) : h("span.muted", "single match")),
      h("td", x.videos.length ? h("a", { href: "#/inspect/video/" + encodeURIComponent(x.videos[0]), onclick: (e) => e.stopPropagation(), title: x.videos.join(", ") }, "▶ video")
        : h("span.muted", "—"))));
    const tableEl = h("table", h("thead", h("tr", ["#", "played", "team A", "score", "team B", "length", "tournament", "video"].map((c, i) => h("th" + ([0, 3, 5].includes(i) ? ".num" : ""), c)))), h("tbody", rows));
    if (more) out.querySelector("tbody").append(...rows);
    else clear(out, r.total ? h("div.scroll", tableEl) : h("p.muted", "No games match these filters."));
    const shown = offset + r.rows.length;
    out.querySelector(".more")?.remove();
    if (shown < r.total) out.append(h("div.more.row", { style: { marginTop: "8px" } }, h("span.muted", `showing ${shown} of ${r.total}`),
      h("button.btn.small.ghost", { onclick: () => { offset += PAGE; load(true); } }, "show more")));
  };
  clear(el, h("div.card.stack",
    h("div.row", h("div.field", h("label", "show"), scope), h("div.field", h("label", "tournament"), tour), h("div.field", h("label", "bot"), bot),
      h("div.field", h("label", "length"), len), h("label.check", { style: { marginTop: "16px" } }, vid, "only games with a video"))),
    h("div", { style: { margin: "12px 0 8px" } }, header), out);
  await load();
}

// ---------------------------------------------------------------- one match
async function match(el, id) {
  const m = await get("/api/inspect/matches/" + id);
  current = id;
  const st = m.stats || {}; const ts = st.team_stats || {};
  const keys = Object.keys(ts.A || {});
  const player = h("div");
  const showVideo = (rel) => clear(player, h("video", { src: "/media/videos/" + rel, controls: true, autoplay: true }), h("div.muted.mono", rel));
  if (m.videos.length) showVideo(m.videos[0]);
  else clear(player, h("div.card.muted", "No video of this game yet: use Render on the left (about a minute for a 4-minute game)."));
  const evBox = h("div");
  const back = m.tournament_id ? [h("a", { href: resultsLink({ tournament: m.tournament_id }) }, "← games of " + (m.tournament || "tournament")), h("a", { href: "#/play/tournament/" + m.tournament_id }, "standings")]
    : [h("a", { href: "#/inspect/results" }, "← all results")];
  clear(el,
    h("div.row", back, h("span.muted", "match #" + m.id), h("a.btn.right", { href: "/aflhub/?match=" + m.id, title: "watch this match in AFLHub" }, "3D replay"),
    h("button.btn", { title: "replay it live as the retro broadcast (sound, video export)", onclick: () => openMatch(m.id).catch((e) => toast("Couldn't open the replay: " + (e.message || e), "bad")) }, "👾 Watch"),
    window.AFL_META.features.analysis ? h("a.btn.red", { href: "#/inspect/analyse/" + m.id }, window.AFL_META.features.sandbox ? "Analyse ▸ (footage, transcript, sandbox, engine)" : "Analyse ▸ (footage, transcript)") : null),
    h("div.card.row", { style: { marginTop: "8px", gap: "24px" } },
      h("div", h("div.teamA", h("b", m.bot_a)), h("div.muted", "team A · attacks right")),
      h("div.score", h("span.teamA", m.score_a ?? "?"), " – ", h("span.teamB", m.score_b ?? "?")),
      h("div", h("div.teamB", h("b", m.bot_b)), h("div.muted", "team B")),
      h("div.right.muted", `${m.seconds} s · seed ${m.seed ?? "?"} · engine v${m.engine_version} · ${m.result || ""}`, h("br"),
        `${when(m.created)} · ` + (m.tournament ? `tournament ${m.tournament}` : (m.source || "").startsWith("legacy") ? m.source.replace("legacy:", "history: ") : "single match"))),
    h("div.grid2", { style: { gridTemplateColumns: "minmax(300px, 380px) 1fr", marginTop: "14px" } },
      h("div.stack",
        h("div.card.stack", h("h3", { style: { marginTop: 0 } }, "video"),
          m.videos.length ? h("div.stack", m.videos.map((v) => h("a", { href: "javascript:void 0", onclick: () => showVideo(v) }, "▶ " + v))) : null,
          m.replayable ? h("div.row",
            h("button.btn", { onclick: () => startJob("render", { match_id: m.id, speed: 2 }) }, m.videos.length ? "Render again" : "Render video"),
            window.AFL_META.features.value_model ? h("button.btn.ghost", { onclick: () => startJob("render", { match_id: m.id, speed: 2, value_bar: true }) }, "…with value bar") : null)
            : h("div.muted", "This game can't be replayed (no log and no seed)."),
          h("div.muted", { style: { fontSize: "12px" } }, m.log_path ? "log: " + m.log_path : "no stored log: code-bot games are re-simulated exactly for video")),
        h("div.card", h("h3", { style: { marginTop: 0 } }, "team stats"), keys.length ? table([{ key: "k", label: "" }, { key: "a", label: "A", num: true }, { key: "b", label: "B", num: true }],
          keys.map((k) => ({ k, a: ts.A[k], b: (ts.B || {})[k] }))) : h("p.muted", "No statistics stored (imported history).")),
        h("div.card.stack", h("h3", { style: { marginTop: 0 } }, "bots"),
          h("div.mono", { style: { fontSize: "12px" } }, `A ${m.bot_a}  #${m.hash_a}`), h("div.mono", { style: { fontSize: "12px" } }, `B ${m.bot_b}  #${m.hash_b}`),
          h("div.row", h("a", { href: "#/develop/bot/" + encodeURIComponent(m.bot_a) }, "A's code"), h("a", { href: "#/develop/bot/" + encodeURIComponent(m.bot_b) }, "B's code"),
            h("a", { href: resultsLink({ bot: m.bot_a }) }, "A's games"), h("a", { href: resultsLink({ bot: m.bot_b }) }, "B's games")))),
      h("div.stack", player, evBox)));
  const ev = await get(`/api/inspect/matches/${id}/events`);
  const interesting = ev.events.filter((e) => ["score", "mark", "tackle", "turnover", "spoil", "out_on_the_full", "set_play"].includes(e.type));
  clear(evBox, h("details", h("summary", `events (${ev.events.length}; ${interesting.length} key ones)`),
    ev.note ? h("p.muted", ev.note) : h("div.scroll", { style: { maxHeight: "40vh" } }, table([{ key: "t", label: "t", num: true }, { key: "type", label: "event" },
      { key: "d", label: "detail" }], interesting.map((e) => ({ t: e.t, type: e.type, d: JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k]) => !["t", "type"].includes(k)))).slice(0, 140) }))))));
}

// ---------------------------------------------------------------- videos
function oneVideo(el, rel) {
  const m = rel.match(/^(\d+)(?:_|\.mp4)/);
  clear(el, h("div.row", h("a", { href: "#/inspect/videos" }, "← video library"), m ? h("a", { href: "#/inspect/match/" + m[1] }, "match #" + m[1] + " (details, events)") : null),
    h("video", { src: "/media/videos/" + rel, controls: true, autoplay: true, style: { marginTop: "10px" } }), h("div.muted.mono", rel));
}

async function videos(el) {
  const vids = await get("/api/inspect/videos");
  const mine = vids.filter((v) => !v.archive), old = vids.filter((v) => v.archive);
  const cols = [{ key: "path", label: "video" }, { key: "match_id", label: "match", num: true }, { key: "size_mb", label: "MB", num: true }, { key: "modified", label: "made" }];
  const open = (v) => { location.hash = "#/inspect/video/" + encodeURIComponent(v.path); };
  clear(el,
    h("h3", `Rendered from stored games (${mine.length})`),
    mine.length ? h("div.scroll", { style: { maxHeight: "40vh" } }, table(cols, mine, open)) : h("p.muted", "None yet: render one from a match page."),
    h("h3", `From the old repo (${old.length})`),
    old.length ? h("div.scroll", { style: { maxHeight: "40vh" } }, table(cols.filter((c) => c.key !== "match_id"), old, open)) : h("p.muted", "None."));
}
