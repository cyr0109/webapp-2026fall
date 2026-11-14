import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "./api";

/** 開啟邀請連結後自動加入群組，成功就進入該群組的帳本。 */
export default function Join() {
  const { token } = useParams();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const sent = useRef(false); // React 開發模式會跑兩次 effect，只送一次

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    api(`/invites/${token}/join`, { method: "POST" })
      .then((group) => navigate(`/g/${group.id}`, { replace: true }))
      .catch((err) => setError(err.message));
  }, [token, navigate]);

  return (
    <main className="sheet">
      <div className="block">
        {error ? <p className="notice">{error}</p> : <p className="empty">加入群組中</p>}
      </div>
    </main>
  );
}
