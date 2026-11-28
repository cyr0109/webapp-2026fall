import { useState } from "react";
import { useOutletContext } from "react-router-dom";
import ConfirmDialog from "./ConfirmDialog";
import { api } from "./api";
import { money, shortDate, settlementStamp } from "./format";

export default function History() {
  const { expenses, settlements, group, groupId, me, nameOf, run } = useOutletContext();
  const [undoId, setUndoId] = useState(null);

  return (
    <section className="block">
      <div className="block-head">
        <h2 className="block-title">結算紀錄</h2>
        {settlements.length > 0 && <span className="block-note">{settlements.length} 次</span>}
      </div>

      {settlements.length === 0 ? (
        <p className="empty">尚無結算紀錄。在帳本勾選項目即可結算。</p>
      ) : (
        settlements.map((s, index) => {
          const covered = expenses.filter((e) => e.settlement_id === s.id);
          const total = covered.reduce((sum, e) => sum + e.amount, 0);
          const paid = s.transfers
            .filter((t) => t.from_member_id === me)
            .reduce((sum, t) => sum + t.amount, 0);
          const received = s.transfers
            .filter((t) => t.to_member_id === me)
            .reduce((sum, t) => sum + t.amount, 0);

          return (
            // 最新的一次預設展開：結算完會被導到這裡，要馬上看到結果
            <details key={s.id} className="settlement" open={index === 0}>
              <summary>
                <span className="row-main">
                  <span className="row-title">
                    {nameOf(s.initiated_by_member_id)} 結算 {covered.length} 筆
                  </span>
                  <span className="row-meta">
                    {settlementStamp(s.created_at)}，共 {money(total)}
                  </span>
                </span>
                {paid > 0 ? (
                  <span className="figure debit">你付 {money(paid)}</span>
                ) : received > 0 ? (
                  <span className="figure">你收 {money(received)}</span>
                ) : (
                  <span className="figure muted-figure">與你無關</span>
                )}
              </summary>

              <div className="settlement-body">
                <h4 className="block-title">應付款</h4>
                {s.transfers.length === 0 ? (
                  <p className="empty">無需轉帳，各自負擔已相抵。</p>
                ) : (
                  <ul className="rows">
                    {s.transfers.map((t) => (
                      <li key={t.id} className="row">
                        <div className="row-main">
                          {nameOf(t.from_member_id)}
                          <span className="balance-verb">付給</span>
                          {nameOf(t.to_member_id)}
                          <span className="row-meta">
                            {t.paid_at ? `已收款 ${settlementStamp(t.paid_at)}` : "待付款"}
                          </span>
                          {!t.paid_at && t.due_on && <span className="row-meta">繳款期限 {t.due_on}</span>}
                          {!t.paid_at && t.to_member_id === me && (
                            <button
                              className="quiet"
                              onClick={() =>
                                run(() =>
                                  api(
                                    `/groups/${groupId}/settlements/${s.id}/transfers/${t.id}/paid`,
                                    { method: "POST" }
                                  )
                                )
                              }
                            >
                              確認收到
                            </button>
                          )}
                        </div>
                        {/* 紅色只代表「你要付出去的錢」，收進來的用一般墨色 */}
                        <span className={t.from_member_id === me ? "figure debit" : "figure"}>
                          {money(t.amount)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}

                <h4 className="block-title">涵蓋項目</h4>
                <ul className="rows">
                  {covered.map((e) => (
                    <li key={e.id} className="row settled">
                      <div className="row-main">
                        <span className="date-col">{shortDate(e.spent_on)}</span>
                        <span className="row-title">{e.description}</span>
                        <span className="row-meta">
                          {nameOf(e.payer_member_id)} 墊付，
                          {Object.keys(e.shares).length} 人分攤
                        </span>
                      </div>
                      <span className="figure">{money(e.amount)}</span>
                    </li>
                  ))}
                </ul>

                {s.transfers.some((t) => t.paid_at) ? (
                  <p className="empty">已有人確認收款，這次結算不能復原。</p>
                ) : (s.initiated_by_member_id === me || group.i_am_admin) && (
                  <>
                    <button
                      className="quiet danger"
                      onClick={() => setUndoId(s.id)}
                    >
                      復原這次結算
                    </button>
                    <p className="empty">復原後，涵蓋的項目會退回未結，可以再編輯。</p>
                  </>
                )}
              </div>
            </details>
          );
        })
      )}
      {undoId !== null && (
        <ConfirmDialog
          title="復原這次結算"
          onCancel={() => setUndoId(null)}
          onConfirm={() => {
            const id = undoId;
            setUndoId(null);
            run(() => api(`/groups/${groupId}/settlements/${id}`, { method: "DELETE" }));
          }}
        >
          <p>涵蓋的項目會退回帳本，可以再編輯。</p>
        </ConfirmDialog>
      )}
    </section>
  );
}
