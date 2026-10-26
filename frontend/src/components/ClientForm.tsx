"use client";

import { useState } from "react";
import { ErrorAlert, Modal } from "@/components/ui";
import { api } from "@/lib/api";

export type Client = {
  id: string; name: string; external_reference: string | null; tax_id: string | null; notes: string | null;
  status: string; created_at: string; updated_at: string;
};

export function ClientForm({ initial, onSaved, onClose }: { initial?: Client; onSaved: () => void; onClose: () => void }) {
  const [form, setForm] = useState({
    name: initial?.name ?? "", external_reference: initial?.external_reference ?? "", tax_id: initial?.tax_id ?? "",
    notes: initial?.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = { ...form, external_reference: form.external_reference || null, tax_id: form.tax_id || null, notes: form.notes || null };
    try {
      if (initial) await api(`/clients/${initial.id}`, { method: "PATCH", body });
      else await api("/clients", { method: "POST", body });
      onSaved();
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={initial ? "Editar empresa" : "Nova empresa atendida"} onClose={onClose} actions={
      <>
        <button className="btn" onClick={onClose}>Cancelar</button>
        <button className="btn primary" onClick={save} disabled={busy || form.name.trim().length < 2}>{busy ? "Salvando…" : "Salvar"}</button>
      </>
    }>
      <ErrorAlert error={error} />
      <div className="stack">
        <label className="field">Razão social / nome
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />
        </label>
        <div className="form-grid">
          <label className="field">Código interno (opcional)
            <input value={form.external_reference} onChange={(e) => setForm({ ...form, external_reference: e.target.value })} />
          </label>
          <label className="field">CNPJ (opcional)
            <input value={form.tax_id} onChange={(e) => setForm({ ...form, tax_id: e.target.value })} />
          </label>
        </div>
        <label className="field">Observações
          <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} style={{ fontFamily: "inherit" }} />
        </label>
      </div>
    </Modal>
  );
}
