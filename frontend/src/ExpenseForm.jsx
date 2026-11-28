import { useState } from "react";
import { api } from "./api";
import { money, taipeiStamp } from "./format";

const today = () => taipeiStamp(new Date()).slice(0, 10);

/** 跟後端 split.equal_shares 同一條規則：除不盡的餘數由墊付人吸收，墊付人未分攤則給第一人。
 *  這裡只負責預填數字讓使用者看得到，最終仍由後端驗證加總。 */
function previewEqualShares(amount, ids, payerId) {
  if (!ids.length || !amount) return {};
  const base = Math.floor(amount / ids.length);
  const shares = Object.fromEntries(ids.map((id) => [id, base]));
  const absorber = ids.includes(payerId) ? payerId : ids[0];
  shares[absorber] += amount - base * ids.length;
  return shares;
}

export default function ExpenseForm({ groupId, members, myMemberId, editing, onSaved, onCancel }) {
  const active = members.filter((m) => m.status === "active");
  const [payerMemberId, setPayerMemberId] = useState(editing?.payer_member_id ?? myMemberId);
  const [amount, setAmount] = useState(editing?.amount ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [spentOn, setSpentOn] = useState(editing?.spent_on ?? today());
  const [dueOn, setDueOn] = useState(editing?.due_on ?? "");
  const [participants, setParticipants] = useState(
    editing ? Object.keys(editing.shares).map(Number) : active.map((m) => m.id)
  );
  const [custom, setCustom] = useState(() => {
    if (!editing) return false;
    const equal = previewEqualShares(editing.amount, participants, editing.payer_member_id);
    return participants.some((id) => equal[id] !== editing.shares[id]);
  });
  const [shares, setShares] = useState(editing?.shares ?? {});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const total = Number(amount) || 0;
  const allocated = participants.reduce((sum, id) => sum + (Number(shares[id]) || 0), 0);
  const gap = total - allocated;

  function toggleParticipant(id) {
    setParticipants((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  }

  function enableCustom() {
    setShares(previewEqualShares(total, participants, payerMemberId));
    setCustom(true);
  }

  async function submit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    const body = {
      payer_member_id: payerMemberId,
      amount: total,
      description,
      spent_on: spentOn,
      due_on: dueOn || null,
      ...(custom
        ? { shares: Object.fromEntries(participants.map((id) => [id, Number(shares[id]) || 0])) }
        : { participant_member_ids: participants }),
    };
    try {
      await api(
        editing ? `/groups/${groupId}/expenses/${editing.id}` : `/groups/${groupId}/expenses`,
        { method: editing ? "PUT" : "POST", body }
      );
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="entry-form">
      <h3>{editing ? "編輯項目" : "新增項目"}</h3>

      <div className="grid-2">
        <label className="field">
          <span>項目</span>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="例如：衛生紙"
            required
          />
        </label>
        <label className="field">
          <span>金額</span>
          <input
            type="number"
            min="1"
            step="1"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>墊付人</span>
          <select value={payerMemberId} onChange={(e) => setPayerMemberId(Number(e.target.value))}>
            {active.map((m) => (
              <option key={m.id} value={m.id}>
                {m.username}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>支出日期</span>
          <input
            type="date"
            value={spentOn}
            onChange={(e) => setSpentOn(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>繳款期限（選填）</span>
          <input type="date" value={dueOn} onChange={(e) => setDueOn(e.target.value)} />
        </label>
      </div>

      <fieldset>
        <legend>分攤成員</legend>
        {active.map((m) => (
          <div key={m.id} className="split-row">
            <label className="check">
              <input
                type="checkbox"
                checked={participants.includes(m.id)}
                onChange={() => toggleParticipant(m.id)}
              />
              {m.username}
            </label>
            {custom && participants.includes(m.id) && (
              <input
                type="number"
                min="0"
                step="1"
                className="split-amount"
                aria-label={`${m.username} 分攤金額`}
                value={shares[m.id] ?? 0}
                onChange={(e) => setShares({ ...shares, [m.id]: e.target.value })}
              />
            )}
          </div>
        ))}

        {custom ? (
          <div className={gap === 0 ? "split-status" : "split-status short"}>
            <span>
              已分配 {money(allocated)}
              {gap !== 0 &&
                `，${gap > 0 ? `尚差 ${money(gap)}` : `超出 ${money(-gap)}`}`}
            </span>
            <button type="button" className="quiet" onClick={() => setCustom(false)}>
              改回平均分攤
            </button>
          </div>
        ) : (
          <div className="split-status">
            <span>依人數平均分攤，除不盡的餘額由墊付人負擔。</span>
            <button type="button" className="quiet" onClick={enableCustom}>
              改為自訂金額
            </button>
          </div>
        )}
      </fieldset>

      {error && <p className="notice">{error}</p>}

      <div className="actions">
        <button type="submit" disabled={busy || participants.length === 0}>
          {editing ? "儲存變更" : "新增項目"}
        </button>
        {onCancel && (
          <button type="button" className="ghost" onClick={onCancel}>
            取消
          </button>
        )}
      </div>
    </form>
  );
}
