import { useEffect, useState } from "react";
import { api, readInboxEvents } from "./api";

export function useGroupInbox(groupId, onInboxChange) {
  const [inbox, setInbox] = useState(null);
  const [inboxError, setInboxError] = useState("");
  const [toast, setToast] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let knownIds = null;
    let retry;
    let expireToast;

    async function refresh(requestSignal) {
      const result = await api(`/groups/${groupId}/notifications`, { signal: requestSignal });
      if (requestSignal.aborted) return;
      const initialized = knownIds !== null;
      const fresh = initialized
        ? result.items.filter((item) => !item.is_read && !knownIds.has(item.id))
        : [];
      knownIds = new Set(result.items.map((item) => item.id));
      setInbox(result);
      setInboxError("");
      if (fresh.length) {
        setToast(fresh.length === 1 ? fresh[0].summary : `收到 ${fresh.length} 則新通知`);
        window.clearTimeout(expireToast);
        expireToast = window.setTimeout(() => setToast(null), 6000);
      }
      await onInboxChange(requestSignal);
    }

    async function listen() {
      try {
        await readInboxEvents(groupId, signal, refresh);
      } catch (err) {
        if (signal.aborted) return;
        if ([401, 403, 404].includes(err.status)) {
          setInbox(null);
          setToast(null);
          setInboxError(err.message);
          return;
        }
        if (!knownIds) setInboxError("通知連線中斷，正在重新連線。");
      }
      if (!signal.aborted) retry = window.setTimeout(listen, 2000);
    }

    listen();
    return () => {
      controller.abort();
      window.clearTimeout(retry);
      window.clearTimeout(expireToast);
    };
  }, [groupId, onInboxChange]);

  return { inbox, inboxError, toast };
}
