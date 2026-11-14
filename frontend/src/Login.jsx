import { useState } from "react";
import { api, saveAuth } from "./api";

export default function Login({ onDone }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const path = isRegister ? "/auth/register" : "/auth/login";
      saveAuth(await api(path, { method: "POST", body: { username, password } }));
      onDone();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="entry-page">
      <span className="wordmark">分帳簿</span>
      <p className="tagline">記錄合租共同支出，隨時結算。</p>

      <form onSubmit={submit}>
        <label className="field">
          <span>帳號</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            minLength={2}
          />
        </label>
        <label className="field">
          <span>密碼</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={isRegister ? "new-password" : "current-password"}
            required
            minLength={6}
          />
        </label>

        {error && <p className="notice">{error}</p>}

        <button type="submit" disabled={busy}>
          {isRegister ? "建立帳號" : "登入"}
        </button>
      </form>

      <div className="switch-mode">
        <button
          className="quiet"
          onClick={() => {
            setMode(isRegister ? "login" : "register");
            setError("");
          }}
        >
          {isRegister ? "已有帳號，改為登入" : "還沒有帳號？建立一個"}
        </button>
      </div>
    </main>
  );
}
