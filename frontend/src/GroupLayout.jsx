import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { api } from "./api";

/** 三個畫面（帳本／結算紀錄／成員）共用的外框：載一次資料，發給子畫面。 */
export default function GroupLayout() {
  const { groupId } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [group, expenses, debts, settlements] = await Promise.all([
        api(`/groups/${groupId}`),
        api(`/groups/${groupId}/expenses`),
        api(`/groups/${groupId}/balance`),
        api(`/groups/${groupId}/settlements`),
      ]);
      setData({ group, expenses, debts, settlements });
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, [groupId]);

  useEffect(() => {
    load();
  }, [load]);

  /** 執行一個動作後重新載入。成功回傳 true，失敗顯示訊息並回傳 false。 */
  const run = useCallback(
    async (fn) => {
      setError("");
      try {
        await fn();
        await load();
        return true;
      } catch (err) {
        setError(err.message);
        return false;
      }
    },
    [load]
  );

  if (!data) {
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
          </nav>
        </header>

        <Outlet context={{ ...data, groupId, me: group.my_member_id, nameOf, run, reload: load }} />

        {error && (
          <div className="block">
            <p className="notice">{error}</p>
          </div>
        )}
      </main>
    </>
  );
}
