"use client";

import { useEffect, useRef } from "react";

import { Icon } from "@/components/ui/icon";

export function ActionDialog({ open, title, description, label, value, confirmLabel, dangerous = false, busy = false, onChange, onClose, onConfirm }: { open: boolean; title: string; description: string; label?: string; value?: string; confirmLabel: string; dangerous?: boolean; busy?: boolean; onChange?: (value: string) => void; onClose: () => void; onConfirm: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog className="action-dialog" onCancel={onClose} ref={dialogRef}>
      <div className="dialog-head"><div><p className="eyebrow">Confirm action</p><h2>{title}</h2></div><button aria-label="Close dialog" className="icon-button" onClick={onClose} type="button"><Icon name="close" /></button></div>
      <p>{description}</p>
      {label ? <label>{label}<input autoFocus className="input" onChange={(event) => onChange?.(event.target.value)} type={label.toLowerCase().includes("email") ? "email" : "text"} value={value || ""} /></label> : null}
      <div className="dialog-actions"><button className="button button-ghost" disabled={busy} onClick={onClose} type="button">Cancel</button><button className={`button ${dangerous ? "button-danger-solid" : "button-primary"}`} disabled={busy || Boolean(label && !value?.trim())} onClick={onConfirm} type="button">{busy ? "Working..." : confirmLabel}</button></div>
    </dialog>
  );
}
