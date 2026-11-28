// 同源路徑，由 Vite 的 proxy 轉給後端（設定在 vite.config.js）。
const BASE = "/api";

export function getToken() {
  return localStorage.getItem("token");
}

export function saveAuth({ token, user_id, username }) {
  localStorage.setItem("token", token);
  localStorage.setItem("user_id", user_id);
  localStorage.setItem("username", username);
}

export function clearAuth() {
  localStorage.clear();
}

export function currentUsername() {
  return localStorage.getItem("username");
}

async function request(path, { method = "GET", body, signal, headers } = {}) {
  const token = getToken();
  const res = await fetch(BASE + path, {
    method,
    signal,
    headers: {
      ...headers,
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  if (res.status === 401 && token === getToken()) {
    clearAuth();
    window.location.reload();
  }
  return res;
}

/** 呼叫後端。失敗時丟出帶有後端訊息的 Error。 */
export async function api(path, options) {
  const res = await request(path, options);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw Object.assign(new Error(errorMessage(data, res.status)), { status: res.status });
  return data;
}

/** 讀取 HouseMate 的通知變更事件。串流只送變更信號，通知內容從原 API 讀取。 */
export async function readInboxEvents(groupId, signal, onInbox) {
  const connection = new AbortController();
  const close = () => connection.abort();
  signal.addEventListener("abort", close, { once: true });
  if (signal.aborted) close();
  let timeout;
  let reader;
  const expectHeartbeat = () => {
    window.clearTimeout(timeout);
    // A proxy may leave a dead connection open instead of reporting an error.
    timeout = window.setTimeout(close, 30000);
  };

  try {
    expectHeartbeat();
    const res = await request(`/groups/${groupId}/notifications/events`, {
      signal: connection.signal, headers: { Accept: "text/event-stream" },
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw Object.assign(new Error(errorMessage(data, res.status)), { status: res.status });
    }
    if (!res.body || !res.headers.get("content-type")?.startsWith("text/event-stream")) {
      throw new Error("無法建立通知連線");
    }
    reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let pending = "";
    while (!connection.signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      expectHeartbeat();
      pending += value;
      const frames = pending.split("\n\n");
      pending = frames.pop();
      if (frames.some((frame) => frame.startsWith("event: inbox\n"))) await onInbox(connection.signal);
    }
  } finally {
    window.clearTimeout(timeout);
    signal.removeEventListener("abort", close);
    close();
    if (reader) {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}

/** FastAPI 的 detail 可能是字串，也可能是欄位驗證錯誤的陣列。 */
function errorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => e.msg).join("、");
  return `發生錯誤 (${status})`;
}
