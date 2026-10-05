"""LLM providers: a small vendor-neutral interface plus an OpenAI chat-completions implementation
(plain HTTPS, no SDK), a disk cache, and a fake provider for tests.

Credentials: OPENAI_API_KEY from the environment, else from a .env file (this project's, then
--env-file). Keys are never written anywhere by this code.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

def _default_env_files():
    from aflsim.paths import home
    return (os.path.join(home(), ".env"),)                                    # the repo's .env (gitignored); never printed


DEFAULT_ENV_FILES = None


def load_env(paths=None, override=False):
    for path in (paths or _default_env_files()):
        if path and os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if override or k not in os.environ:
                    os.environ[k] = v


NET_RETRIES = 7                                   # attempts per call for DNS / connection / timeout failures
NET_BACKOFF = (2, 4, 8, 15, 30, 60)               # seconds between attempts: an outage of a couple of minutes is survived


class Provider:
    name = "base"

    def complete(self, system: str, user: str, schema: dict, temperature: float | None) -> tuple[dict, dict]:
        """Return (parsed JSON object, info dict with tokens / latency / model)."""
        raise NotImplementedError


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model="gpt-5.6-terra", api_key=None, base_url="https://api.openai.com/v1", reasoning_effort="medium", timeout=240, max_tokens=8000,
                 api_key_env="OPENAI_API_KEY", vendor="openai"):
        load_env()
        self.vendor = vendor
        self.model = model; self.base_url = base_url.rstrip("/"); self.timeout = timeout; self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self.api_key = api_key or os.environ.get(api_key_env)
        if not self.api_key:
            raise SystemExit("%s not set: put it in the repo's .env (see .env.example) or the environment" % api_key_env)
        self._supports_temperature = True
        self._json_mode = "schema"                 # "schema" (OpenAI json_schema) or "object" (plain JSON mode with the schema in the prompt)
        self._max_tokens_key = "max_completion_tokens"

    def _post(self, body):
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def _post_net(self, body):
        """_post with retries on network-level failures (DNS lookup, connection reset, read timeout). HTTP errors are raised at once."""
        for attempt in range(NET_RETRIES):
            try:
                return self._post(body)
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if attempt >= NET_RETRIES - 1:
                    raise RuntimeError("network error after %d attempts: %s" % (NET_RETRIES, str(e)[:200]))
                time.sleep(NET_BACKOFF[min(attempt, len(NET_BACKOFF) - 1)])

    def _body(self, system, user, schema, temperature):
        if self._json_mode == "schema":
            fmt = {"type": "json_schema", "json_schema": schema}
        else:                                                  # plain JSON mode (or none): describe the schema in the prompt instead
            system = system + "\n\nRespond with a single JSON object matching this JSON schema exactly (no extra keys, no prose):\n" + json.dumps(schema["schema"])
            fmt = {"type": "json_object"} if self._json_mode == "object" else None
        body = {"model": self.model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                self._max_tokens_key: self.max_tokens}
        if fmt is not None:
            body["response_format"] = fmt
        if self.vendor == "deepseek":                          # V4: thinking is on by default; "none" effort = non-thinking mode (fast, cheap)
            body["thinking"] = {"type": "enabled" if self.reasoning_effort else "disabled"}
            if self.reasoning_effort:
                self._supports_temperature = False               # thinking mode rejects temperature
        return body

    _JSON_RANK = {"schema": 0, "object": 1, "none": 2}

    def _downgrade_json_mode(self, used):
        """Step the JSON mode down from the mode a rejected body was built with, never back up (threads share this object)."""
        target = min(self._JSON_RANK[used] + 1, 2)
        if self._JSON_RANK[self._json_mode] < target:
            self._json_mode = {0: "schema", 1: "object", 2: "none"}[target]

    def complete(self, system, user, schema, temperature):
        mode_used = self._json_mode
        body = self._body(system, user, schema, temperature)
        if temperature is not None and self._supports_temperature:
            body["temperature"] = temperature
        if self.reasoning_effort:
            body["reasoning_effort"] = {"medium": "high", "high": "max"}.get(self.reasoning_effort, self.reasoning_effort) if self.vendor == "deepseek" else self.reasoning_effort
        t0 = time.time()
        for attempt in range(6):
            try:
                out = self._post_net(body)
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")
                if e.code == 400 and "temperature" in msg and "temperature" in body:
                    self._supports_temperature = False; body.pop("temperature"); continue
                if e.code == 400 and "reasoning_effort" in msg and "reasoning_effort" in body:
                    body.pop("reasoning_effort"); self.reasoning_effort = None; continue
                if e.code == 400 and ("json_schema" in msg or "response_format" in msg) and "response_format" in body:
                    self._downgrade_json_mode(mode_used); mode_used = self._json_mode
                    body = self._body(system, user, schema, temperature); continue                      # json_schema -> json_object -> prompt only
                if e.code == 400 and self._max_tokens_key == "max_completion_tokens" and "max_completion_tokens" in msg:
                    self._max_tokens_key = "max_tokens"; body = self._body(system, user, schema, temperature); continue
                if e.code in (429, 500, 502, 503) and attempt < 5:
                    time.sleep(NET_BACKOFF[min(attempt, len(NET_BACKOFF) - 1)]); continue
                raise RuntimeError("API error %d from %s: %s" % (e.code, self.base_url, msg[:500]))
        text = out["choices"][0]["message"]["content"]
        reasoning = out["choices"][0]["message"].get("reasoning_content") or ""
        usage = out.get("usage", {})
        info = {"model": out.get("model", self.model), "latency_s": round(time.time() - t0, 2), "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "cached_prompt_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", usage.get("prompt_cache_hit_tokens")),
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"), "cached": False,
                "reasoning_summary": reasoning[:2000]}
        try:
            return json.loads(text), info
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1]), info
            raise RuntimeError("model returned non-JSON: %s" % text[:200])


VENDORS = {
    # prefix -> (base_url, api key variable, api kind); a model is written "vendor:model", e.g. deepseek:deepseek-chat
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "responses"),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", "chat"),      # models (Sept 2026): deepseek-flash, deepseek-v4-pro
}


def make_provider(model_spec: str, reasoning_effort=None, api="responses", **kw) -> Provider:
    """'gpt-5.6-terra' (OpenAI) or 'deepseek:deepseek-chat'. OpenAI uses the Responses API unless api="chat";
    other vendors use chat completions with the JSON-mode fallback. Reasoning effort is sent only where the vendor accepts it
    (dropped automatically otherwise)."""
    vendor, _, model = model_spec.partition(":") if ":" in model_spec else ("openai", "", model_spec)
    if vendor not in VENDORS:
        raise SystemExit("unknown vendor prefix %r (known: %s)" % (vendor, ", ".join(VENDORS)))
    base_url, key_env, kind = VENDORS[vendor]
    if vendor == "openai" and api == "responses":
        return OpenAIResponsesProvider(model=model, reasoning_effort=reasoning_effort, **kw)
    return OpenAIProvider(model=model, base_url=base_url, reasoning_effort=reasoning_effort, api_key_env=key_env, vendor=vendor, **kw)


class OpenAIResponsesProvider(OpenAIProvider):
    """The same contract through OpenAI's Responses API (POST /v1/responses): structured output via
    text.format, reasoning effort via reasoning.effort, and the model's reasoning summary returned in
    info["reasoning_summary"] so the logs can keep why a decision was made. Stateless: every call
    stands alone, which keeps the disk cache exact."""
    name = "openai-responses"
    api = "responses"

    def __init__(self, model="gpt-5.6-terra", api_key=None, base_url="https://api.openai.com/v1", reasoning_effort="medium", timeout=240,
                 max_tokens=8000, reasoning_summary="detailed", api_key_env="OPENAI_API_KEY"):
        super().__init__(model, api_key, base_url, reasoning_effort, timeout, max_tokens, api_key_env=api_key_env)
        self.reasoning_summary = reasoning_summary
        self._supports_summary = True

    def _post(self, body):
        req = urllib.request.Request(self.base_url + "/responses", data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)

    def complete(self, system, user, schema, temperature):
        body = {"model": self.model, "instructions": system, "input": [{"role": "user", "content": user}],
                "text": {"format": {"type": "json_schema", "name": schema["name"], "schema": schema["schema"], "strict": bool(schema.get("strict", False))}},
                "max_output_tokens": self.max_tokens, "store": False}
        if temperature is not None and self._supports_temperature:
            body["temperature"] = temperature
        if self.reasoning_effort or self.reasoning_summary:
            body["reasoning"] = {}
            if self.reasoning_effort:
                body["reasoning"]["effort"] = self.reasoning_effort
            if self.reasoning_summary and self._supports_summary:
                body["reasoning"]["summary"] = self.reasoning_summary
        t0 = time.time()
        for attempt in range(6):
            try:
                out = self._post_net(body)
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")
                if e.code == 400 and "temperature" in msg and "temperature" in body:
                    self._supports_temperature = False; body.pop("temperature"); continue
                if e.code == 400 and "summary" in msg and body.get("reasoning", {}).get("summary"):
                    self._supports_summary = False; body["reasoning"].pop("summary"); continue
                if e.code == 400 and "effort" in msg and body.get("reasoning", {}).get("effort"):
                    body["reasoning"].pop("effort"); self.reasoning_effort = None; continue
                if e.code in (429, 500, 502, 503) and attempt < 5:
                    time.sleep(NET_BACKOFF[min(attempt, len(NET_BACKOFF) - 1)]); continue
                raise RuntimeError("OpenAI API error %d: %s" % (e.code, msg[:500]))
        text, summary = "", []
        for item in out.get("output", []):
            if item.get("type") == "reasoning":
                summary += [s.get("text", "") for s in item.get("summary", []) if s.get("text")]
            elif item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        text += c.get("text", "")
                    elif c.get("type") == "refusal":
                        raise RuntimeError("model refused: %s" % c.get("refusal", "")[:200])
        if not text:
            raise RuntimeError("model returned no text (status %s, incomplete: %s)" % (out.get("status"), out.get("incomplete_details")))
        usage = out.get("usage", {})
        info = {"model": out.get("model", self.model), "latency_s": round(time.time() - t0, 2), "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"), "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
                "cached_prompt_tokens": (usage.get("input_tokens_details") or {}).get("cached_tokens"),
                "reasoning_summary": "\n".join(summary)[:2000], "cached": False}
        try:
            return json.loads(text), info
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start:end + 1]), info
            raise RuntimeError("model returned non-JSON: %s" % text[:200])


class CachedProvider(Provider):
    """Wraps a provider with a content-addressed disk cache (model + temperature + prompts)."""

    def __init__(self, inner: Provider, cache_dir: str):
        self.inner = inner; self.cache_dir = cache_dir; self.name = inner.name
        os.makedirs(cache_dir, exist_ok=True)

    def complete(self, system, user, schema, temperature):
        key = hashlib.sha256(json.dumps([getattr(self.inner, "model", self.inner.name), temperature, getattr(self.inner, "reasoning_effort", None),
                                         getattr(self.inner, "api", "chat"), getattr(self.inner, "base_url", ""), system, user]).encode()).hexdigest()
        path = os.path.join(self.cache_dir, key + ".json")
        if os.path.exists(path):
            d = json.load(open(path, encoding="utf-8"))
            info = dict(d["info"]); info["cached"] = True
            return d["response"], info
        response, info = self.inner.complete(system, user, schema, temperature)
        json.dump({"response": response, "info": info}, open(path, "w", encoding="utf-8"))
        return response, info


class FakeProvider(Provider):
    """Deterministic stand-in for tests and dry runs: answers with a fixed function of the state."""
    name = "fake"

    def __init__(self, fn=None):
        self.fn = fn; self.calls = 0

    def complete(self, system, user, schema, temperature):
        self.calls += 1
        state = json.loads(user.split("Current state:\n", 1)[1].split("\n\n", 1)[0])
        if self.fn is not None:
            return self.fn(state), {"model": "fake", "latency_s": 0.0, "cached": False}
        info = {"model": "fake", "latency_s": 0.0, "cached": False}
        name = schema.get("name") if isinstance(schema, dict) else None
        if name == "coach_plan":
            team = "A" if "team A (players" in system else "B"
            return {"prediction": "fake coach: the ball will be contested at the centre", "summary": "fake plan: kick long, contest everything",
                    "assignments": [{"player": p["id"], "assignment": "contest the ball"} for p in state["team_" + team]], "instructions": ["if loose then contest"]}, info
        if name == "player_action":
            pid = user.split("You are ", 1)[1].split(".", 1)[0].strip()
            team = pid[0]
            acts = self._team_actions(state, team)
            mine = next((a for a in acts if a["player"] == pid), {"player": pid, "action": "HOLD"})
            return {"prediction": "fake player prediction", "intent": "fake player: %s" % mine["action"], "action": {k: v for k, v in mine.items() if k != "player"}}, info
        team = "A" if "You are team A" in system else "B"
        return {"prediction": "fake prediction", "intent": "fake provider: kick long, contest everything", "actions": self._team_actions(state, team)}, info

    @staticmethod
    def _team_actions(state, team):
        mine = state["team_" + team]
        holder = state["ball"]["owner"]
        goal_x = state["goals"]["%s_scores_at_x" % team]
        acts = []
        for p in mine:
            if p["id"] == holder:
                acts.append({"player": p["id"], "action": "KICK", "target": [goal_x + (5.0 if goal_x > 45 else -5.0), 0.0], "power": 1.0})
            elif state["ball"]["state"] != "held":
                acts.append({"player": p["id"], "action": "ATTEMPT_MARK" if state["ball"]["state"] == "flight" else "ATTEMPT_POSSESSION"})
            elif holder and holder[0] != team:
                acts.append({"player": p["id"], "action": "TACKLE", "opponent": holder})
            else:
                acts.append({"player": p["id"], "action": "MOVE", "target": [min(max(p["pos"][0] + (20 if goal_x > 45 else -20), 5), 85), p["pos"][1]]})
        return acts
