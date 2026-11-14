import { useOutletContext } from "react-router-dom";
import { api } from "./api";

export default function Members() {
  const { group, groupId, me, run } = useOutletContext();

  const setStatus = (memberId, status) =>
    run(() =>
      api(`/groups/${groupId}/members/${memberId}`, { method: "PATCH", body: { status } })
    );

  function remove(member) {
    // 移出後對方要重新被邀請才能回來，先確認
    if (confirm(`確定要把 ${member.username} 移出群組嗎？\n對方將無法再看到這個群組，需要重新邀請。`)) {
      setStatus(member.id, "removed");
    }
  }

  return (
    <section className="block">
      <div className="block-head">
        <h2 className="block-title">成員</h2>
        <span className="block-note">{group.members.length} 人</span>
      </div>

      <ul className="rows">
        {group.members.map((m) => {
          const tags = [
            m.id === me ? "你" : null,
            m.is_admin ? "管理員" : null,
            m.status === "deactivated" ? "已停用" : null,
          ].filter(Boolean);
          return (
            <li key={m.id} className="row">
              <div className="row-main">
                <span className="row-title">{m.username}</span>
                {tags.length > 0 && <span className="row-meta">{tags.join("、")}</span>}
              </div>
              {m.id !== me && (
                <div className="row-actions">
                  <button
                    className="quiet"
                    onClick={() =>
                      setStatus(m.id, m.status === "active" ? "deactivated" : "active")
                    }
                  >
                    {m.status === "active" ? "停用" : "啟用"}
                  </button>
                  {group.i_am_admin && (
                    <button className="quiet danger" onClick={() => remove(m)}>
                      移出群組
                    </button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <p className="empty" style={{ marginTop: 12 }}>
        停用的成員不會出現在新項目中，既有未結款項仍照常計算。移出群組則會解除對方的存取權，
        但他記過的項目與分攤紀錄都會保留。
      </p>
    </section>
  );
}
