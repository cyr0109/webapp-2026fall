import { useCallback, useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { api } from "./api";
import { taipeiStamp } from "./format";

const toInput = (iso) => iso ? taipeiStamp(iso).replace(" ", "T") : "";
const toISO = (local) => `${local}:00+08:00`;
const empty = { availabilities: [], "garbage-schedules": [], chores: [] };

function DateField({ label, value, onChange }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type="datetime-local" value={value} onChange={(e) => onChange(e.target.value)} required />
    </label>
  );
}

function EntryForm({ title, onSave, onCancel, encode, children }) {
  const [busy, setBusy] = useState(false);
  return (
    <form className="entry-form" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      try {
        await onSave(encode());
      } finally {
        setBusy(false);
      }
    }}>
      <h3>{title}</h3>
      {children}
      <div className="actions">
        <button disabled={busy}>儲存</button>
        <button type="button" className="ghost" disabled={busy} onClick={onCancel}>取消</button>
      </div>
    </form>
  );
}

function AvailabilityForm({ row, ...actions }) {
  const [starts, setStarts] = useState(toInput(row.starts_at));
  const [ends, setEnds] = useState(toInput(row.ends_at));
  return (
    <EntryForm {...actions} title={row.id ? "編輯空檔" : "新增空檔"}
      encode={() => ({ starts_at: toISO(starts), ends_at: toISO(ends) })}>
      <div className="grid-2">
        <DateField label="開始時間" value={starts} onChange={setStarts} />
        <DateField label="結束時間" value={ends} onChange={setEnds} />
      </div>
    </EntryForm>
  );
}

function GarbageForm({ row, ...actions }) {
  const [time, setTime] = useState(toInput(row.arrives_at));
  const [location, setLocation] = useState(row.location ?? "");
  return (
    <EntryForm {...actions} title={row.id ? "編輯垃圾車時間" : "新增垃圾車時間"}
      encode={() => ({ arrives_at: toISO(time), location: location.trim() })}>
      <div className="grid-2">
        <DateField label="抵達時間" value={time} onChange={setTime} />
        <label className="field">
          <span>停靠地點</span>
          <input required maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} />
        </label>
      </div>
    </EntryForm>
  );
}

function ChoreForm({ row, members, schedules, ...actions }) {
  const [title, setTitle] = useState(row.title ?? "");
  const [scheduled, setScheduled] = useState(toInput(row.scheduled_at));
  const [assigned, setAssigned] = useState(row.assigned_member_id ?? "");
  const [linked, setLinked] = useState(row.garbage_schedule_id ?? "");
  const choices = members.filter((member) => member.status === "active");
  if (row.completed_at && !choices.some((member) => member.id === assigned)) {
    choices.push({ id: assigned, username: members.find((member) => member.id === assigned)?.username ?? `成員 ${assigned}` });
  }

  return (
    <EntryForm {...actions} title={row.id ? "編輯家務" : "指派家務"}
      encode={() => ({
        title: title.trim(), scheduled_at: toISO(scheduled), assigned_member_id: Number(assigned),
        garbage_schedule_id: linked || null,
      })}>
      <div className="grid-2">
        <label className="field">
          <span>家務名稱</span>
          <input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span>受指派成員</span>
          <select required disabled={Boolean(row.completed_at)} value={assigned}
            onChange={(e) => setAssigned(e.target.value)}>
            <option value="">請選擇成員</option>
            {choices.map((member) => <option key={member.id} value={member.id}>{member.username}</option>)}
          </select>
        </label>
        <label className="field">
          <span>關聯垃圾車時間（選填）</span>
          <select value={linked} onChange={(e) => {
            const id = Number(e.target.value);
            setLinked(id || "");
            const match = schedules.find((schedule) => schedule.id === id);
            if (match) setScheduled(toInput(match.arrives_at));
          }}>
            <option value="">無</option>
            {schedules.map((schedule) => (
              <option key={schedule.id} value={schedule.id}>
                {taipeiStamp(schedule.arrives_at)} · {schedule.location}
              </option>
            ))}
          </select>
        </label>
        <DateField label="家務時間" value={scheduled} onChange={setScheduled} />
      </div>
    </EntryForm>
  );
}

function RowActions({ onEdit, onDelete, children }) {
  return (
    <div className="row-actions">
      {children}
      {onEdit && <button className="quiet" onClick={onEdit}>編輯</button>}
      {onDelete && <button className="quiet danger" onClick={onDelete}>刪除</button>}
    </div>
  );
}

export default function Household() {
  const { groupId, group, me, nameOf } = useOutletContext();
  const base = `/groups/${groupId}`;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(null);
  const active = group.members.some((member) => member.id === me && member.status === "active");

  const load = useCallback(async () => {
    const keys = Object.keys(empty);
    const rows = await Promise.all(keys.map((key) => api(`${base}/${key}`)));
    return Object.fromEntries(keys.map((key, index) => [key, rows[index]]));
  }, [base]);

  useEffect(() => {
    let disposed = false;
    load().then((rows) => {
      if (!disposed) setData(rows);
    }).catch((err) => {
      if (!disposed) setError(err.message);
    });
    return () => { disposed = true; };
  }, [load]);

  async function mutate(path, method, body) {
    setError("");
    try {
      await api(`${base}/${path}`, { method, body });
      setEditing(null);
      setData(await load());
    } catch (err) {
      setError(err.message);
    }
  }

  function edit(kind, row = {}) {
    setError("");
    setEditing({ kind, row });
  }

  function form(kind, Component, props = {}) {
    if (editing?.kind !== kind) return null;
    const { row } = editing;
    return <Component key={row.id ?? "new"} {...props} row={row} onCancel={() => setEditing(null)}
      onSave={(body) => mutate(row.id ? `${kind}/${row.id}` : kind, row.id ? "PUT" : "POST", body)} />;
  }

  function remove(kind, row) {
    if (window.confirm("確定刪除這筆資料？")) mutate(`${kind}/${row.id}`, "DELETE");
  }

  if (!data) return <p className={error ? "notice" : "empty"}>{error || "載入中"}</p>;
  const schedules = data["garbage-schedules"];

  return (
    <>
      <section className="block">
        <div className="block-head">
          <h2 className="block-title">空檔</h2>
          {active && <button onClick={() => edit("availabilities")}>新增空檔</button>}
        </div>
        <p className="empty">所有時間皆為台北時間。</p>
        {form("availabilities", AvailabilityForm)}
        {data.availabilities.length === 0 && <p className="empty">尚無成員登記空檔。</p>}
        <ul className="rows">
          {data.availabilities.map((row) => (
            <li className="row" key={row.id}>
              <div className="row-main">
                <span className="row-title">{nameOf(row.member_id)}</span>
                <span className="row-meta">{taipeiStamp(row.starts_at)} ～ {taipeiStamp(row.ends_at)}</span>
              </div>
              {row.member_id === me && (
                <RowActions onEdit={active ? () => edit("availabilities", row) : null}
                  onDelete={() => remove("availabilities", row)} />
              )}
            </li>
          ))}
        </ul>
      </section>
      <section className="block">
        <div className="block-head">
          <h2 className="block-title">垃圾車時間</h2>
          {group.i_am_admin && <button onClick={() => edit("garbage-schedules")}>新增垃圾車時間</button>}
        </div>
        {form("garbage-schedules", GarbageForm)}
        {schedules.length === 0 && <p className="empty">尚無垃圾車時間。</p>}
        <ul className="rows">
          {schedules.map((row) => (
            <li className="row" key={row.id}>
              <div className="row-main">
                <span className="row-title">{row.location}</span>
                <span className="row-meta">{taipeiStamp(row.arrives_at)}</span>
                <span className="row-meta">
                  {row.available_member_ids.length > 0 ? `可到場：${row.available_member_ids.map(nameOf).join("、")}` : "目前無成員有空"}
                </span>
              </div>
              <RowActions onEdit={group.i_am_admin ? () => edit("garbage-schedules", row) : null}
                onDelete={group.i_am_admin ? () => remove("garbage-schedules", row) : null}>
                {active && <button className="quiet" onClick={() => edit("chores", {
                  title: "倒垃圾", scheduled_at: row.arrives_at, garbage_schedule_id: row.id,
                  assigned_member_id: row.available_member_ids[0],
                })}>指派倒垃圾</button>}
              </RowActions>
            </li>
          ))}
        </ul>
      </section>
      <section className="block">
        <div className="block-head">
          <h2 className="block-title">家務</h2>
          {active && <button onClick={() => edit("chores")}>指派家務</button>}
        </div>
        {form("chores", ChoreForm, { members: group.members, schedules })}
        {data.chores.length === 0 && <p className="empty">尚無家務。</p>}
        <ul className="rows">
          {data.chores.map((row) => {
            const manage = row.created_by_member_id === me || group.i_am_admin;
            return (
              <li className="row" key={row.id}>
                <div className="row-main">
                  <span className="row-title">{row.title}</span>
                  <span className="row-meta">{taipeiStamp(row.scheduled_at)} · {nameOf(row.assigned_member_id)}</span>
                  <span className="row-meta">{row.completed_at ? `已完成 ${taipeiStamp(row.completed_at)}` : "待完成"}</span>
                </div>
                <RowActions onEdit={manage ? () => edit("chores", row) : null}
                  onDelete={manage ? () => remove("chores", row) : null}>
                  {!row.completed_at && row.assigned_member_id === me && (
                    <button className="quiet" onClick={() => mutate(`chores/${row.id}/complete`, "PATCH")}>標記完成</button>
                  )}
                </RowActions>
              </li>
            );
          })}
        </ul>
      </section>
      {error && <p className="notice household-error" role="alert">{error}</p>}
    </>
  );
}
