import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "./api";

export default function Groups() {
  const navigate = useNavigate();
  const [groups, setGroups] = useState(null);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api("/groups").then(setGroups).catch((err) => setError(err.message));
  }, []);

  async function create(e) {
    e.preventDefault();
    setError("");
    try {
      const group = await api("/groups", { method: "POST", body: { name } });
      setName("");
      navigate(`/g/${group.id}`);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <main className="sheet">
      <div className="block">
        <div className="block-head">
          <h2 className="block-title">群組</h2>
          {groups?.length > 0 && <span className="block-note">{groups.length}</span>}
        </div>

        {groups === null ? (
          <p className="empty">載入中</p>
        ) : groups.length === 0 ? (
          <p className="empty">尚未加入任何群組。建立一個開始記帳。</p>
        ) : (
          <ul className="rows">
            {groups.map((g) => (
              <li key={g.id} className="row">
                <div className="row-main">
                  <div className="row-title">{g.name}</div>
                  <div className="row-meta">
                    {g.members.map((m) => m.username).join("、")}
                  </div>
                </div>
                <Link className="quiet" to={`/g/${g.id}`}>
                  開啟
                </Link>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={create} className="inline-form">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="群組名稱，例如：民生東路 3F"
            aria-label="群組名稱"
            required
          />
          <button type="submit">建立群組</button>
        </form>

        {error && <p className="notice">{error}</p>}
      </div>
    </main>
  );
}
