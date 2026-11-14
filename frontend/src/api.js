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

/** 呼叫後端。失敗時丟出帶有後端訊息的 Error。 */
export async function api(path, { method = "GET", body } = {}) {
  const token = getToken();
  const res = await fetch(BASE + path, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  if (res.status === 401) {
    clearAuth();
    window.location.reload();
    throw new Error("請重新登入");
  }
  if (res.status === 204) return null;

  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(errorMessage(data, res.status));
  return data;
}

/** FastAPI 的 detail 可能是字串，也可能是欄位驗證錯誤的陣列。 */
function errorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => e.msg).join("、");
  return `發生錯誤 (${status})`;
}
