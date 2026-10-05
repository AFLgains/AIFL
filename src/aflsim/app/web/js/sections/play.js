// PLAY: matches, tournaments (build, run, standings), rating a bot, the ladder.
import { get, post } from "../api.js";
import { h, clear, toast, field, check, table, when, botPicker, bots } from "../ui.js";
import { startJob } from "../jobs.js";
import { openLive } from "../analysis/snes.js";

const TABS = [["live", "🕹 Play it yourself"], ["match", "Match"], ["tournament", "Tournaments"], ["rate", "Rate a bot"], ["ladder", "Ladder"]];

export async function render(view, route, meta) {
  const [page = "match", ...arg] = route;
  const body = h("div");
  clear(view, h("h1", "Play"), h("div.muted", "Pick teams and play: a match, a series, a tournament. Everything runs as a job and lands in the results store."),
    h("div.tabs", TABS.map(([id, t]) => h("a" + (id === page ? ".on" : ""), { href: "#/play/" + id }, t))), body);
  if (page === "live") return liveTab(body, meta);
  if (page === "match") return matchTab(body, meta);
  if (page === "tournament") return arg.length ? standings(body, Number(arg[0])) : tournamentTab(body, meta);
  if (page === "rate") return rateTab(body, meta);
  if (page === "ladder") return ladderTab(body, arg[0]);
}

// a sensible default bot: the highest-rated code bot in this library, else the built-in rules team
async function strongest(fallback = "zoo:rules") {
  const list = await bots(); let best = null;
  for (const b of list) { if (b.kind !== "code") continue; const r = b.rating_240 ?? b.rating_120 ?? null; if (r !== null && (!best || r > best[0])) best = [r, b.spec]; }
  return best ? best[1] : fallback;
}

const num = (value, attrs = {}) => h("input", { type: "number", value, style: { width: "110px" }, ...attrs });

async function matchTab(el, meta) {
  const pre = JSON.parse(sessionStorage.getItem("afl.match") || "{}"); sessionStorage.removeItem("afl.match");
  const a = await botPicker("Team A (attacks right)", pre.bot_a || await strongest());
  const b = await botPicker("Team B", pre.bot_b || "zoo:ontario");
  const seconds = num(meta.default_seconds), seed = num(1), games = num(1, { min: 1 }), parallel = num(8, { min: 1 });
  const both = h("input", { type: "checkbox" }), video = h("input", { type: "checkbox", checked: true }), vbar = h("input", { type: "checkbox" });
  clear(el, h("div.card.stack",
    h("div.row", a, b),
    h("div.row", field("seconds", seconds), field("seed", seed), field("games (seeds)", games), field("parallel", parallel)),
    h("div.row", check("both ends (also play each seed with the teams swapped: the fair comparison)", both)),
    h("div.row", check("render video (first game)", video), meta.features.value_model ? check("value bar on the video", vbar) : null),
    h("div.row", h("button.btn.red", { onclick: () => startJob("match", {
      bot_a: a.value(), bot_b: b.value(), seconds: Number(seconds.value), seed: Number(seed.value), games: Number(games.value),
      both_ends: both.checked, video: video.checked, value_bar: vbar.checked, parallel: Number(parallel.value) }) }, "Play"),
      h("span.muted", "Look-ahead games take minutes each; a 240 s code-bot game takes about a second (plus about a minute to render).")),
  ));
}

async function liveTab(el, meta) {
  const opp = await botPicker("Opponent (blue)", "zoo:rules", { lookahead: false });
  const helper = await botPicker("Your teammates are run by", await strongest(), { lookahead: false });
  const seconds = h("select", [[60, "1 minute"], [120, "2 minutes"], [240, "4 minutes (a full game)"]].map(([v, t]) => h("option", { value: v, selected: v === 120 }, t)));
  const go = async () => {
    try { await openLive({ opponent: opp.value(), helper: helper.value(), seconds: Number(seconds.value) }); }
    catch (e) { toast("Couldn't start the game: " + (e.message || e), "bad"); }
  };
  const key = (k, what) => h("tr", h("td", h("kbd", k)), h("td", what));
  clear(el, h("div.card.stack",
    h("h3", { style: { margin: 0 } }, "Play it yourself"),
    h("p.muted", { style: { margin: 0 } }, `You're red (attacking right), controlling one player at a time; your teammates are run by the bot you pick. Real engine, real rules (${meta.game} engine v${meta.engine_version}).`),
    h("div.row", opp, helper, field("length", seconds)),
    h("div.row", h("button.btn.red", { onclick: go }, "▶ Kick off")),
    h("table", { style: { maxWidth: "760px" } }, h("tbody",
      key("Arrows / WASD", "run (Shift: sprint, burns energy)"),
      key("Space (with the ball)", "kick: hold to fill the power meter (that's the distance), aim with the arrows, let go before the red or it sprays. Aim at the goals in range to shoot."),
      key("Space (ball in the air)", "leap for the mark: a ring shows where it comes down; press when it turns green. Too early and you're locked out for a moment."),
      key("Space (loose ball / their ball)", "go and gather it / tackle their carrier (get close first)"),
      key("J", "handball to the teammate you're pointing at"), key("L", "spoil (punch the ball away, same timing as a mark)"),
      key("Q", "switch to the teammate best placed for the ball (dashed circle). Hold Q and press an arrow: the teammate that way."),
      key("Esc", "quit"))),
    h("p.muted", { style: { margin: 0 } }, "Control also moves on its own: to your ball carrier, to the receiver of your kick, to whoever is best placed for their kick or a loose ball.")));
}

async function rateTab(el, meta) {
  const bot = await botPicker("Bot to rate", await strongest());
  const seconds = num(meta.default_seconds), games = num(10), panel = num(16), parallel = num(8);
  const lad = await get("/api/play/ladders");
  clear(el, h("div.card.stack",
    h("div.muted", "Plays the bot against a spread of rated opponents (both ends, common seeds) and fits its rating with theirs fixed. The games are stored, so the bot joins the ladder."),
    bot, h("div.row", field("seconds", seconds), field("seeds per opponent", games), field("opponents", panel), field("parallel", parallel)),
    h("div.muted", "Ladders available: " + (lad.map((l) => `${l.seconds} s (${l.bots} bots, ${l.n} games)`).join(" · ") || "none yet")),
    h("button.btn.red", { onclick: () => startJob("rate", { bot: bot.value(), seconds: Number(seconds.value), games: Number(games.value), panel: Number(panel.value), parallel: Number(parallel.value) }) }, "Rate")));
}

async function ladderTab(el, secs) {
  const lads = await get("/api/play/ladders");
  if (!lads.length) return clear(el, h("div.card.muted", "No ladder yet. Run tournaments/ladder_240.toml (Tournaments tab), or import the old one."));
  const s = Number(secs || (lads.find((l) => l.seconds === 240) || lads[lads.length - 1]).seconds);
  const t = await get("/api/play/ladder?seconds=" + s);
  clear(el,
    h("div.row", lads.map((l) => h("a.chip", { href: "#/play/ladder/" + l.seconds, style: l.seconds === s ? { borderColor: "#1e88e5" } : null }, `${l.seconds} s · ${l.bots} bots · ${l.n} games`))),
    h("p.muted", "Bradley-Terry over every stored game at this length (current bot versions only); the anchors zone / ontario / rules / runner / keeper average 1500."),
    h("div.scroll", table([{ key: "rank", label: "#", num: true }, { key: "bot", label: "bot" }, { key: "rating", label: "rating", num: true }, { key: "games", label: "games", num: true }],
      t.rows.map((r, i) => ({ ...r, rank: i + 1 })), (r) => { location.hash = "#/develop/bot/" + encodeURIComponent(r.bot); })));
}

async function tournamentTab(el, meta) {
  const [configs, past] = await Promise.all([get("/api/play/tournament-configs"), get("/api/play/tournaments")]);
  const cfgList = h("div.stack", configs.map((c) => h("div.job",
    h("div.row", h("span.title.grow", c.file), h("span.chip", c.format || "?"), h("span.chip", (c.seconds || "?") + " s"),
      h("button.btn.small", { onclick: () => startJob("tournament", { file: c.file, parallel: 8 }) }, "Run / resume")),
    h("details", h("summary.muted", "config"), h("pre.log", c.text)))));
  const pastT = past.length ? table([{ key: "id", label: "id", num: true }, { key: "name", label: "name" }, { key: "status", label: "status" }, { key: "games", label: "games", num: true },
    { key: "created", label: "started", fmt: when }], past.slice().reverse(), (t) => { location.hash = "#/play/tournament/" + t.id; }) : h("p.muted", "None yet.");
  clear(el, h("div.grid2", { style: { gridTemplateColumns: "minmax(380px, 1fr) minmax(380px, 1fr)" } },
    h("div.stack", h("h2", "Build a tournament"), await builder(meta)),
    h("div.stack", h("h2", "Saved configs"), cfgList, h("h2", "Tournaments played"), h("div.scroll", pastT))));
}

async function builder(meta) {
  const name = h("input", { value: "my_cup" });
  const fmt = h("select", ["round_robin", "groups", "gauntlet", "ladder"].map((f) => h("option", { value: f }, f)));
  const seconds = num(meta.default_seconds), seeds = num(5), seed = num(100000), finals = num(2);
  const allowLLM = h("input", { type: "checkbox" }), library = h("input", { type: "checkbox" });
  const picker = await botPicker("add a bot", "", { blank: true });
  let groups = { A: [], B: [] };
  let current = "A";
  let field_ = [];
  const zone = h("div.stack");
  const draw = () => {
    const f = fmt.value;
    const chips = (arr) => h("div.chips", arr.length ? arr.map((b, i) => h("span.chip", b, h("button", { onclick: () => { arr.splice(i, 1); draw(); } }, "×"))) : h("span.muted", "none yet"));
    if (f === "groups") {
      clear(zone, h("div.row", Object.keys(groups).map((g) => h("button.btn.small" + (g === current ? "" : ".ghost"), { onclick: () => { current = g; draw(); } }, "group " + g)),
        h("button.btn.small.ghost", { onclick: () => { const g = String.fromCharCode(65 + Object.keys(groups).length); groups[g] = []; current = g; draw(); } }, "+ group")),
        Object.entries(groups).map(([g, arr]) => h("div", h("label", "group " + g), chips(arr))), field("finals: top N of each group", finals));
    } else if (f === "gauntlet") {
      clear(zone, h("div.muted", "The first bot you add is the challenger; the rest are its field (or tick 'whole library')."), chips(field_), check("field = whole library", library));
    } else {
      clear(zone, chips(field_), check("whole library (every code bot + the anchors)", library));
    }
  };
  fmt.addEventListener("change", draw);
  const add = () => {
    const v = picker.value(); if (!v) return;
    (fmt.value === "groups" ? groups[current] : field_).push(v); picker.set(""); draw();
  };
  draw();
  const save = async (run) => {
    const f = fmt.value;
    const cfg = { name: name.value.trim(), format: f, seconds: Number(seconds.value), seeds: Number(seeds.value), seed: Number(seed.value), allow_llm: allowLLM.checked };
    if (f === "groups") { cfg.groups = groups; cfg.finals = Number(finals.value); }
    else if (f === "gauntlet") { cfg.challenger = field_[0]; cfg.field = library.checked ? "library" : field_.slice(1); }
    else cfg.bots = library.checked ? "library" : field_;
    try {
      const r = await post("/api/play/tournament-configs", { config: cfg, overwrite: true });
      toast("Saved " + r.path.split(/[\\/]/).pop(), "ok");
      if (run) startJob("tournament", { file: cfg.name + ".toml", parallel: 8 });
      location.hash = "#/play/tournament"; window.dispatchEvent(new HashChangeEvent("hashchange"));
    } catch (e) { toast(e.message, "bad"); }
  };
  return h("div.card.stack",
    h("div.row", field("name", name), field("format", fmt)),
    h("div.row", field("seconds", seconds), field("seeds per pairing (x2 ends)", seeds), field("base seed", seed)),
    h("div.row", picker, h("button.btn.small", { onclick: add }, "add")), zone,
    check("allow LLM bots (they cost money)", allowLLM),
    h("div.row", h("button.btn.ghost", { onclick: () => save(false) }, "Save config"), h("button.btn.red", { onclick: () => save(true) }, "Save + run")));
}

async function standings(el, tid) {
  const t = await get("/api/play/tournaments/" + tid);
  const cols = [{ key: "rank", label: "#", num: true }, { key: "bot", label: "bot" }, { key: "p", label: "P", num: true }, { key: "w", label: "W", num: true },
    { key: "l", label: "L", num: true }, { key: "d", label: "D", num: true }, { key: "pts", label: "Pts", num: true }, { key: "pct", label: "%", num: true, fmt: (v) => v.toFixed(1) }];
  // clicking a team opens THIS tournament's games of that team
  const tbl = (rows) => table(cols, rows.map((r, i) => ({ ...r, rank: i + 1 })), (r) => { location.hash = "#/inspect/results?" + new URLSearchParams({ tournament: tid, bot: r.bot }); });
  const ratings = Object.entries(t.ratings || {}).sort((a, b) => b[1] - a[1]);
  clear(el, h("div.row", h("a", { href: "#/play/tournament" }, "← tournaments"), h("h2", { style: { margin: 0 } }, t.tournament.name), h("span.status." + (t.tournament.status === "finished" ? "done" : "running"), t.tournament.status),
    h("span.muted", t.games + " games"), h("a.btn.small.right", { href: "#/inspect/results?tournament=" + tid }, "all games of this tournament →")),
    h("p.muted", "Click a team to see just its games in this tournament."),
    ...Object.entries(t.groups || {}).map(([g, rows]) => [h("h3", "group " + g), h("div.card", tbl(rows))]),
    h("h3", "overall"), h("div.card", tbl(t.overall)),
    h("h3", "ratings (Bradley-Terry over this tournament's games)"),
    h("div.card", table([{ key: "bot", label: "bot" }, { key: "r", label: "rating", num: true }], ratings.map(([bot, r]) => ({ bot, r: Math.round(r) })))));
}
