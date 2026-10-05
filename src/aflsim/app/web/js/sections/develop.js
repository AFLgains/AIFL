// DEVELOP A TEAM: the library, any bot's source, writing code bots, defining LLM (instruction) bots.
import { get, post } from "../api.js";
import { h, clear, toast, field, check, bots, grouped } from "../ui.js";
import { startJob } from "../jobs.js";

let selected = null;
let filter = "";

export async function render(view, route) {
  const [page, ...arg] = route;
  const list = h("div");
  const pane = h("div");
  clear(view,
    h("div.row", h("div", h("h1", "Develop a team"), h("div.muted", "Browse the library, read how any bot plays, write your own" + (window.AFL_META.features.llm ? ", or define an LLM team." : "."))),
      h("div.right.row", h("button.btn", { onclick: () => { location.hash = "#/develop/new-code"; } }, "New code bot"),
        window.AFL_META.features.llm ? h("button.btn.ghost", { onclick: () => { location.hash = "#/develop/new-llm"; } }, "New LLM bot") : null)),
    h("div.grid2", { style: { marginTop: "14px" } }, list, pane));
  await renderList(list);
  if (page === "new-code") return newCode(pane, sessionStorage.getItem("afl.newcode") || null);
  if (page === "new-llm") return newLLM(pane);
  if (page === "bot" && arg.length) { selected = decodeURIComponent(arg.join("/")); return showBot(pane, selected); }
  clear(pane, h("div.card.muted", "Pick a bot on the left to read its code and ratings, or start a new one."));
}

async function renderList(el) {
  const all = await bots();
  const box = h("div.list");
  const input = h("input", { placeholder: "filter bots…", value: filter, style: { width: "100%", marginBottom: "8px" },
    oninput: (e) => { filter = e.target.value.toLowerCase(); fill(); } });
  function fill() {
    const shown = all.filter((b) => !filter || b.spec.toLowerCase().includes(filter));
    clear(box, grouped(shown).map(([g, items]) => [h("div.grp", `${g} (${items.length})`),
      items.map((b) => h("div.item" + (b.spec === selected ? ".on" : ""), { onclick: () => { location.hash = "#/develop/bot/" + encodeURIComponent(b.spec); } },
        h("span", b.spec.replace(/^ladder\//, "")), h("span.r", b.rating_240 ?? b.rating_120 ?? "")))]));
  }
  fill();
  clear(el, input, box, h("div.muted", { style: { fontSize: "12px", marginTop: "6px" } }, "Ratings: the 240 s ladder where it exists, else the imported 120 s one."));
}

async function showBot(pane, spec) {
  const src = await get("/api/develop/source?spec=" + encodeURIComponent(spec));
  const all = await bots();
  const info = all.find((b) => b.spec === spec) || {};
  const ta = h("textarea.code", { value: src.text, readOnly: !(src.editable && src.kind === "code"), spellcheck: false });
  const actions = h("div.row",
    src.editable && src.kind === "code" ? h("button.btn", { onclick: async () => {
      try { await post("/api/develop/code", { name: spec, text: ta.value, overwrite: true }); toast("Saved " + spec, "ok"); bots(true); startJob("check", { bot: spec }); }
      catch (e) { toast(e.message, "bad"); } } }, "Save + check") : null,
    src.kind === "code" && !src.editable ? h("button.btn.ghost", { onclick: () => {
      sessionStorage.setItem("afl.newcode", JSON.stringify({ name: "drafts/" + spec.split("/").pop() + "_v2", text: src.text }));
      location.hash = "#/develop/new-code"; } }, "Copy to drafts to change it") : null,
    h("button.btn.ghost", { onclick: () => startJob("check", { bot: spec }) }, "Check"),
    h("button.btn.ghost", { onclick: () => startJob("rate", { bot: spec, seconds: 240, games: 10 }) }, "Rate (240 s)"),
    h("button.btn.ghost", { onclick: () => { sessionStorage.setItem("afl.match", JSON.stringify({ bot_a: spec })); location.hash = "#/play/match"; } }, "Play it…"),
    h("a.right", { href: "#/inspect/results?bot=" + encodeURIComponent(spec) }, "its games →"));
  clear(pane, h("div.card.stack",
    h("div.row", h("h2", { style: { margin: 0 } }, spec), h("span.chip", src.kind), src.editable ? h("span.chip", "editable") : h("span.chip", "read-only"),
      info.rating_240 ? h("span.chip", `240 s: ${info.rating_240} (${info.games_240} games)`) : null,
      info.rating_120 ? h("span.chip", `120 s: ${info.rating_120} (${info.games_120} games)`) : null),
    h("div.muted.mono", { style: { fontSize: "12px" } }, src.path, " · hash ", src.hash),
    spec.startsWith("llm:") ? h("div.muted", "LLM bots cost API calls when they play; the app runs only one LLM job at a time.") : null,
    actions, ta));
}

async function newCode(pane, prefill) {
  sessionStorage.removeItem("afl.newcode");
  const t = await get("/api/develop/templates");
  const p = prefill ? JSON.parse(prefill) : { name: "drafts/my_bot", text: t.code };
  const name = h("input", { value: p.name, style: { minWidth: "260px" } });
  const ta = h("textarea.code", { value: p.text, spellcheck: false });
  clear(pane, h("div.card.stack",
    h("h2", { style: { margin: 0 } }, "New code bot"),
    h("div.muted", "One Python file with class Bot(team, rules, seed). Subclass RulesController and override _dispose / _forward / _midfielder / _defender, or write choose_actions from scratch. Saved into bots/" + window.AFL_META.game + "/code/, then checked."),
    h("div.row", field("name (community/… or drafts/…)", name),
      h("button.btn", { onclick: async () => {
        try { const r = await post("/api/develop/code", { name: name.value.trim(), text: ta.value }); toast("Saved " + r.spec, "ok"); bots(true);
          startJob("check", { bot: r.spec }); location.hash = "#/develop/bot/" + encodeURIComponent(r.spec); }
        catch (e) { toast(e.message, "bad"); } } }, "Save + check")),
    ta));
}

async function newLLM(pane) {
  const t = await get("/api/develop/templates");
  const type = h("select", Object.keys(t.llm_types).map((k) => h("option", { value: k }, k)));
  const name = h("input", { value: "my_llm_team" });
  const comment = h("input", { value: "", placeholder: "what this team is (a comment in the file)", style: { minWidth: "320px" } });
  const fields = h("div.row");
  const preview = h("pre.log");
  let inputs = {};
  function build() {
    inputs = {};
    const ex = t.llm_examples[type.value];
    clear(fields, t.llm_types[type.value].map((k) => {
      const v = ex[k];
      const inp = typeof v === "boolean" ? h("input", { type: "checkbox", checked: v }) : h("input", { value: v ?? "", type: typeof v === "number" ? "number" : "text", step: "any" });
      inputs[k] = inp;
      inp.addEventListener("input", show); inp.addEventListener("change", show);
      return typeof v === "boolean" ? check(k, inp) : field(k, inp);
    }));
    show();
  }
  function cfg() {
    const c = { type: type.value, comment: comment.value };
    for (const [k, inp] of Object.entries(inputs)) c[k] = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
    return c;
  }
  async function show() {
    try { preview.textContent = (await post("/api/develop/llm/preview", { name: name.value, config: cfg() })).toml; }
    catch (e) { preview.textContent = e.message; }
  }
  type.addEventListener("change", build); comment.addEventListener("input", show);
  build();
  clear(pane, h("div.card.stack",
    h("h2", { style: { margin: 0 } }, "New LLM bot"),
    h("div.muted", "jev: TypeSafe's classifier picks each player's x, y and speed · llm: one model plays the whole team · coached: a coach model plans, a player model acts. Keys come from the repo's .env."),
    h("div.row", field("name (llm:<name>)", name), field("type", type), field("comment", comment)),
    fields, h("h3", "bots/" + window.AFL_META.game + "/llm/" + "<name>.toml"), preview,
    h("div.row", h("button.btn", { onclick: async () => {
      try { const r = await post("/api/develop/llm", { name: name.value.trim(), config: cfg() }); toast("Saved " + r.spec, "ok"); bots(true);
        location.hash = "#/develop/bot/" + encodeURIComponent(r.spec); }
      catch (e) { toast(e.message, "bad"); } } }, "Save"),
      h("span.muted", "Test it for free first with a mock/fake version (llm:jev_mock, llm:fake_llm) in Play."))));
}
