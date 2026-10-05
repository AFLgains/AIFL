// The one place the browser talks to the server. Every call returns parsed JSON or throws an Error with the
// server's message (FastAPI puts it in `detail`).
async function call(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
}

export const get = (url) => call("GET", url);
export const post = (url, body) => call("POST", url, body || {});
export const qs = (params) =>
  Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
