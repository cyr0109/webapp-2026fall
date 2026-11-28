import { useOutletContext } from "react-router-dom";
import { api } from "./api";
import { taipeiStamp } from "./format";

export default function Notifications() {
  const { groupId, inbox, inboxError, run } = useOutletContext();

  return (
    <section className="block">
      <div className="block-head">
        <h2 className="block-title">站內通知</h2>
        {inbox && <span className="block-note">{inbox.unread_count} 則未讀</span>}
      </div>
      {inboxError && <p className="notice">{inboxError}</p>}
      {!inbox && !inboxError && <p className="empty">載入中</p>}
      {inbox?.items.length === 0 && <p className="empty">目前沒有通知。</p>}
      {inbox?.items.length > 0 && (
        <ul className="rows">
          {inbox.items.map((item) => (
            <li className="row" key={item.id}>
              <div className="row-main">
                <span className="row-title">{item.summary}</span>
                <span className="row-meta">{taipeiStamp(item.created_at)}{item.is_read ? " · 已讀" : ""}</span>
              </div>
              {!item.is_read && (
                <button className="quiet" onClick={() => run(() =>
                  api(`/groups/${groupId}/notifications/${item.id}/read`, { method: "PATCH" })
                )}>
                  標為已讀
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
