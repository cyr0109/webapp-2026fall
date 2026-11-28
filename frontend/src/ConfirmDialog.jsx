import { useEffect, useRef } from "react";

export default function ConfirmDialog({ title, children, onCancel, onConfirm }) {
  const dialog = useRef(null);

  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  return (
    <dialog
      ref={dialog}
      className="confirm-dialog"
      aria-labelledby="confirm-title"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <h2 id="confirm-title">{title}</h2>
      {children}
      <div className="actions">
        <button type="button" className="ghost" onClick={onCancel}>取消</button>
        <button type="button" onClick={onConfirm}>確認</button>
      </div>
    </dialog>
  );
}
