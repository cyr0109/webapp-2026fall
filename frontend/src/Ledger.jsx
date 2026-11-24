import { useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";
import { api } from "./api";
import { money, shortDate } from "./format";
import ExpenseForm from "./ExpenseForm";
import ConfirmDialog from "./ConfirmDialog";

export default function Ledger() {
  const { group, expenses, debts, groupId, me, nameOf, run, reload } = useOutletContext();
  const navigate = useNavigate();
  const [selected, setSelected] = useState([]);
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const unsettled = expenses.filter((e) => !e.is_settled);
  const selectedExpenses = unsettled.filter((expense) => selected.includes(expense.id));
  const myDebts = debts.filter((d) => d.from_member_id === me || d.to_member_id === me);
  const otherDebts = debts.filter((d) => d.from_member_id !== me && d.to_member_id !== me);

  const toggle = (id) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  function closeForm() {
    setAdding(false);
    setEditing(null);
  }

  async function settle() {
    setConfirming(false);
    const ok = await run(() =>
      api(`/groups/${groupId}/settlements`, {
        method: "POST",
        body: { expense_ids: selectedExpenses.map((expense) => expense.id) },
      })
    );
    // 結算後跳到紀錄畫面，使用者才看得到該轉多少錢給誰
    if (ok) navigate(`/g/${groupId}/history`);
  }

  return (
    <>
      <section className="block">
        <div className="block-head">
          <h2 className="block-title">結餘</h2>
          <span className="block-note">依據 {unsettled.length} 筆未結項目</span>
        </div>

        {debts.length === 0 ? (
          <p className="empty">目前無未結款項。</p>
        ) : (
          <>
            {myDebts.length === 0 ? (
              <p className="empty">你目前沒有應收或應付款項。</p>
            ) : (
              <ul className="rows">
                {myDebts.map((d, i) => {
                  const iOwe = d.from_member_id === me;
                  return (
                    <li key={i} className="row balance-row">
                      <div className="row-main">
                        <span className="balance-verb">{iOwe ? "應付" : "應收"}</span>
                        <span className="balance-name">
                          {nameOf(iOwe ? d.to_member_id : d.from_member_id)}
                        </span>
                      </div>
                      <span className={iOwe ? "figure debit" : "figure"}>{money(d.amount)}</span>
                    </li>
                  );
                })}
              </ul>
            )}

            {otherDebts.length > 0 && (
              <div className="subledger">
                <h3 className="block-title">其他成員之間</h3>
                <ul className="rows">
                  {otherDebts.map((d, i) => (
                    <li key={i} className="row">
                      <div className="row-main">
                        {nameOf(d.from_member_id)}
                        <span className="balance-verb">應付</span>
                        {nameOf(d.to_member_id)}
                      </div>
                      <span className="figure">{money(d.amount)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      <section className="block">
        <div className="block-head">
          <h2 className="block-title">未結項目</h2>
          {!adding && !editing && <button onClick={() => setAdding(true)}>新增項目</button>}
        </div>

        {(adding || editing) && (
          <ExpenseForm
            key={editing?.id ?? "new"}
            groupId={groupId}
            members={group.members}
            myMemberId={me}
            editing={editing}
            onSaved={() => {
              closeForm();
              reload();
            }}
            onCancel={closeForm}
          />
        )}

        {unsettled.length === 0 ? (
          <p className="empty">沒有未結項目。新增一筆共同支出開始記錄。</p>
        ) : (
          <>
            <ul className="rows">
              {unsettled.map((e) => (
                <li key={e.id} className="row">
                  <div className="row-main">
                    {/* 按鈕不能放進 label，否則點編輯會順手勾到 checkbox */}
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={selected.includes(e.id)}
                        onChange={() => toggle(e.id)}
                      />
                      <span>
                        <span className="date-col">{shortDate(e.spent_on)}</span>
                        <span className="row-title">{e.description}</span>
                      </span>
                    </label>
                    <div className="row-sub indented">
                      <span className="row-meta">
                        {nameOf(e.payer_member_id)} 墊付，
                        {Object.keys(e.shares).length} 人分攤，
                        {e.shares[me] === undefined
                          ? "你未分攤"
                          : `你分攤 ${money(e.shares[me])}`}
                      </span>
                      {e.due_on && <span className="row-meta">繳款期限 {e.due_on}</span>}
                      <span className="row-actions">
                        <button className="quiet" onClick={() => setEditing(e)}>
                          編輯
                        </button>
                        <button
                          className="quiet danger"
                          onClick={() =>
                            run(() =>
                              api(`/groups/${groupId}/expenses/${e.id}`, { method: "DELETE" })
                            )
                          }
                        >
                          刪除
                        </button>
                      </span>
                    </div>
                  </div>
                  <span className="figure">{money(e.amount)}</span>
                </li>
              ))}
            </ul>

            <div className="actions">
              {selectedExpenses.length === 0 ? (
                <>
                  <span className="empty">勾選要一起結算的項目。</span>
                  <button
                    className="quiet"
                    onClick={() => setSelected(unsettled.map((e) => e.id))}
                  >
                    全選
                  </button>
                </>
              ) : (
                <>
                  <button onClick={() => setConfirming(true)}>結算所選 {selectedExpenses.length} 筆</button>
                  <button className="quiet" onClick={() => setSelected([])}>
                    清除選取
                  </button>
                </>
              )}
            </div>
          </>
        )}
      </section>
      {confirming && (
        <ConfirmDialog title="確認結算" onCancel={() => setConfirming(false)} onConfirm={settle}>
          <p>結算 {selectedExpenses.length} 筆，共 {money(selectedExpenses.reduce((sum, e) => sum + e.amount, 0))}。</p>
          <p>結算後項目將鎖定。若要修改，可在確認收款前復原結算。</p>
        </ConfirmDialog>
      )}
    </>
  );
}
