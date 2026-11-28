import { useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { api } from "./api";
import { useGroupInbox } from "./useGroupInbox";

/** 群組分頁共用同一份資料。 */
export default function GroupLayout() {
  const { groupId } = useParams();
  return <GroupView key={groupId} groupId={groupId} />;
}

function GroupView({ groupId }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const nextRequest = useRef(0);
  const appliedRequest = useRef(0);

  const fetchGroup = useCallback(async (signal) => {
    const requestId = ++nextRequest.current;
    const options = { signal };
    const [group, expenses, debts, settlements] = await Promise.all([
      api(`/groups/${groupId}`, options),
      api(`/groups/${groupId}/expenses`, options),
      api(`/groups/${groupId}/balance`, options),
      api(`/groups/${groupId}/settlements`, options),
    ]);
    return { requestId, data: { group, expenses, debts, settlements } };
  }, [groupId]);

  const applyGroup = useCallback(({ requestId, data }) => {
    // Live updates and local actions may finish in a different order.
    if (requestId < appliedRequest.current) return;
    appliedRequest.current = requestId;
    setData(data);
  }, []);

  const refreshFromInbox = useCallback(async (signal) => {
    try {
      const result = await fetchGroup(signal);
      if (!signal.aborted) applyGroup(result);
    } catch {
      // A refresh failure should not replace the user's current view or stop notifications.
    }
  }, [fetchGroup, applyGroup]);
  const { inbox, inboxError, toast } = useGroupInbox(groupId, refreshFromInbox);

  useEffect(() => {
    const controller = new AbortController();
    fetchGroup(controller.signal).then(
      (result) => {
        if (controller.signal.aborted) return;
        applyGroup(result);
        setError("");
      },
      (err) => {
        if (!controller.signal.aborted) setError(err.message);
      },
    );
    return () => controller.abort();
  }, [fetchGroup, applyGroup]);

  /** 執行一個動作後重新載入。成功回傳 true，失敗顯示訊息並回傳 false。 */
  const run = useCallback(
    async (fn) => {
      setError("");
      try {
        if (fn) await fn();
        applyGroup(await fetchGroup());
        setError("");
        return true;
      } catch (err) {
        setError(err.message);
        return false;
      }
    },
    [fetchGroup, applyGroup]
  );
  const reload = useCallback(() => run(), [run]);

  if (!data || String(data.group.id) !== groupId) {
    return (
      <main className="sheet">
        <div className="block">
          {error ? <p className="notice">{error}</p> : <p className="empty">載入中</p>}
        </div>
      </main>
    );
  }

  const { group } = data;
  const nameOf = (id) => group.members.find((m) => m.id === id)?.username ?? `成員 ${id}`;

  return (
    <>
      <Link className="quiet" to="/">
        返回群組列表
      </Link>

      <main className="sheet">
        <header className="sheet-head">
          <h1>{group.name}</h1>
          <div className="roster">{group.members.map((m) => m.username).join("、")}</div>
          <nav className="screen-nav">
            <NavLink to={`/g/${groupId}`} end>
              帳本
            </NavLink>
            <NavLink to={`/g/${groupId}/history`}>結算紀錄</NavLink>
            <NavLink to={`/g/${groupId}/members`}>成員</NavLink>
            <NavLink to={`/g/${groupId}/household`}>共居</NavLink>
            <NavLink to={`/g/${groupId}/notifications`}>
              通知{inbox?.unread_count > 0 && ` (${inbox.unread_count})`}
            </NavLink>
          </nav>
        </header>

        <Outlet context={{ ...data, inbox, inboxError, groupId, me: group.my_member_id, nameOf, run, reload }} />

        {error && (
          <div className="block">
            <p className="notice">{error}</p>
          </div>
        )}
      </main>
      {toast && (
        <aside className="inbox-toast">
          <p role="status">{toast}</p>
          <Link to={`/g/${groupId}/notifications`}>查看通知</Link>
        </aside>
      )}
    </>
  );
}
