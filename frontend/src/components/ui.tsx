"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorDetails, errorMessage } from "@/lib/api";

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row muted" role="status">
      <span className="spinner" /> {label ?? "Carregando…"}
    </span>
  );
}

export function Badge({ kind, children }: { kind?: string; children: React.ReactNode }) {
  return <span className={`badge ${kind ?? ""}`}>{children}</span>;
}

export function Alert({ kind = "info", title, children }: { kind?: "info" | "error" | "warning" | "success"; title?: string; children?: React.ReactNode }) {
  return (
    <div className={`alert ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {title && <strong>{title}</strong>}
      {title && children ? <div>{children}</div> : children}
    </div>
  );
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const details = errorDetails(error);
  return (
    <Alert kind="error" title={errorMessage(error)}>
      {details.length > 0 && (
        <ul>
          {details.slice(0, 12).map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
    </Alert>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function Modal({ title, onClose, children, actions }: { title: string; onClose: () => void; children: React.ReactNode; actions?: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {children}
        {actions && <div className="modal-actions">{actions}</div>}
      </div>
    </div>
  );
}

export function ConfirmButton({ label, confirmText, onConfirm, className = "btn danger small", disabled }: {
  label: string; confirmText: string; onConfirm: () => Promise<void> | void; className?: string; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  return (
    <>
      <button className={className} onClick={() => setOpen(true)} disabled={disabled}>{label}</button>
      {open && (
        <Modal title="Confirmar operação" onClose={() => setOpen(false)} actions={
          <>
            <button className="btn" onClick={() => setOpen(false)} disabled={busy}>Cancelar</button>
            <button className="btn primary" disabled={busy} onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm();
                setOpen(false);
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}>{busy ? "Processando…" : "Confirmar"}</button>
          </>
        }>
          <ErrorAlert error={error} />
          <p>{confirmText}</p>
        </Modal>
      )}
    </>
  );
}

export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <div className="row between" style={{ padding: "10px 12px" }}>
      <span className="muted small">{total.toLocaleString("pt-BR")} registros · página {page} de {pages}</span>
      <div className="row">
        <button className="btn small" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Anterior</button>
        <button className="btn small" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Próxima</button>
      </div>
    </div>
  );
}

/** Carrega dados assíncronos com estados de carregamento e erro. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fnRef.current());
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="muted small">{hint}</div>}
    </div>
  );
}
