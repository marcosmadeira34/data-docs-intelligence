"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, ErrorAlert, Modal } from "@/components/ui";
import { api } from "@/lib/api";
import { CanonicalField, FileAsset, Rule, RuleType } from "@/lib/types";

const OPS: Record<string, string> = {
  eq: "igual a", ne: "diferente de", gt: "maior que", gte: "maior ou igual a", lt: "menor que", lte: "menor ou igual a",
  in: "está na lista", not_in: "não está na lista", is_null: "está vazio", not_null: "está preenchido", contains: "contém",
  starts_with: "começa com", ends_with: "termina com",
};
const FORMATS: Record<string, string> = { cpf: "CPF", cnpj: "CNPJ", cpf_cnpj: "CPF ou CNPJ", email: "E-mail", cep: "CEP", uf: "UF", digits: "Somente dígitos", phone_br: "Telefone" };
const TYPES: Record<string, string> = { integer: "Inteiro", decimal: "Número", date: "Data", boolean: "Sim/não", tax_id: "CPF/CNPJ", text: "Texto" };

type Cond = { field: string; op: string; value?: any; value_field?: string };
type Group = { mode: "all" | "any"; items: Cond[] };

const toGroup = (g: any): Group => g ? { mode: g.all ? "all" : "any", items: (g.all ?? g.any ?? []).filter((c: any) => c.field) } : { mode: "all", items: [] };
const fromGroup = (g: Group) => ({ [g.mode]: g.items.map((c) => {
  const out: any = { field: c.field, op: c.op };
  if (c.value_field) out.value_field = c.value_field;
  else if (!["is_null", "not_null"].includes(c.op)) out.value = ["in", "not_in"].includes(c.op) ? String(c.value ?? "").split(";").map((s) => s.trim()).filter(Boolean) : c.value;
  return out;
}) });

function FieldSelect({ value, onChange, fields, allowEmpty }: { value?: string; onChange: (v: string) => void; fields: CanonicalField[]; allowEmpty?: boolean }) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
      {allowEmpty && <option value="">—</option>}
      {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
    </select>
  );
}

export function ConditionBuilder({ label, group, setGroup, fields }: { label: string; group: Group; setGroup: (g: Group) => void; fields: CanonicalField[] }) {
  const upd = (i: number, patch: Partial<Cond>) => setGroup({ ...group, items: group.items.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  return (
    <div className="card" style={{ background: "var(--surface-2)" }}>
      <div className="row" style={{ marginBottom: 8 }}>
        <strong>{label}</strong>
        <select value={group.mode} onChange={(e) => setGroup({ ...group, mode: e.target.value as Group["mode"] })}>
          <option value="all">todas as condições</option>
          <option value="any">qualquer condição</option>
        </select>
      </div>
      {group.items.map((c, i) => (
        <div key={i} className="row" style={{ marginBottom: 6 }}>
          <FieldSelect value={c.field} onChange={(v) => upd(i, { field: v })} fields={fields} />
          <select value={c.op} onChange={(e) => upd(i, { op: e.target.value })}>
            {Object.entries(OPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {!["is_null", "not_null"].includes(c.op) && (
            <>
              <select value={c.value_field ? "field" : "value"} onChange={(e) => upd(i, e.target.value === "field" ? { value_field: fields[0].key, value: undefined } : { value_field: undefined, value: "" })}>
                <option value="value">valor</option>
                <option value="field">outro campo</option>
              </select>
              {c.value_field ? <FieldSelect value={c.value_field} onChange={(v) => upd(i, { value_field: v })} fields={fields} /> : (
                <input value={Array.isArray(c.value) ? c.value.join("; ") : c.value ?? ""} onChange={(e) => upd(i, { value: e.target.value })}
                  placeholder={["in", "not_in"].includes(c.op) ? "valores separados por ;" : "valor"} />
              )}
            </>
          )}
          <button className="btn small" onClick={() => setGroup({ ...group, items: group.items.filter((_, j) => j !== i) })}>Remover</button>
        </div>
      ))}
      <button className="btn small" onClick={() => setGroup({ ...group, items: [...group.items, { field: fields[0]?.key ?? "", op: "eq", value: "" }] })}>Adicionar condição</button>
    </div>
  );
}

export function RuleForm({ initial, catalog, fields, onSaved, onClose }: {
  initial?: Rule; catalog: RuleType[]; fields: CanonicalField[]; onSaved: () => void; onClose: () => void;
}) {
  const [ruleType, setRuleType] = useState(initial?.rule_type ?? "required");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [severity, setSeverity] = useState(initial?.severity ?? "error");
  const [status, setStatus] = useState(initial?.status ?? "active");
  const [message, setMessage] = useState(initial?.message ?? "");
  const [clientId, setClientId] = useState(initial?.client_account_id ?? "");
  const [p, setP] = useState<Record<string, any>>(initial?.params ?? { field: fields[0]?.key });
  const [when, setWhen] = useState<Group>(toGroup(initial?.params?.when));
  const [then, setThen] = useState<Group>(toGroup(initial?.params?.then ?? initial?.params?.assert));
  const [applies, setApplies] = useState<Group>(toGroup(initial?.applies_when));
  const [error, setError] = useState<unknown>(null);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [clients, setClients] = useState<{ id: string; name: string }[]>([]);
  const [files, setFiles] = useState<FileAsset[]>([]);
  const meta = catalog.find((c) => c.type === ruleType);

  useEffect(() => {
    api("/clients", { query: { status: "active", limit: 200 } }).then((r) => setClients(r.items)).catch(() => undefined);
    if (ruleType === "cross_file") api("/files", { query: { limit: 200 } }).then((r) => setFiles(r.items)).catch(() => undefined);
  }, [ruleType]);
  const refFile = useMemo(() => files.find((f) => f.id === p.reference_file_id), [files, p.reference_file_id]);
  const [refColumns, setRefColumns] = useState<string[]>([]);
  useEffect(() => {
    if (!p.reference_file_id) return setRefColumns([]);
    api<FileAsset>(`/files/${p.reference_file_id}`).then((f) => setRefColumns(f.inspection?.columns.map((c) => c.name) ?? [])).catch(() => setRefColumns([]));
  }, [p.reference_file_id, refFile]);

  const params = (): Record<string, any> => {
    switch (ruleType) {
      case "dependency": return { when: fromGroup(when), then: fromGroup(then) };
      case "custom": return { ...(when.items.length ? { when: fromGroup(when) } : {}), assert: fromGroup(then) };
      case "allowed_values": return { ...p, values: typeof p.values === "string" ? p.values.split(";").map((s: string) => s.trim()).filter(Boolean) : p.values };
      default: return p;
    }
  };
  const body = () => ({ name, description: description || null, rule_type: ruleType, params: params(), severity, status,
    message: message || null, applies_when: applies.items.length ? fromGroup(applies) : null });

  const check = async () => {
    setError(null);
    try {
      await api("/validation-rules/check", { method: "POST", body: { rule_type: ruleType, params: params(), applies_when: body().applies_when } });
      setChecked(true);
    } catch (e) {
      setChecked(false);
      setError(e);
    }
  };
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (initial) {
        const { rule_type, ...patch } = body();
        await api(`/validation-rules/${initial.id}`, { method: "PATCH", body: patch });
      } else {
        await api("/validation-rules", { method: "POST", body: { ...body(), client_id: clientId || null } });
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const field = (key = "field", label = "Campo") => (
    <label className="field">{label}<FieldSelect value={p[key]} onChange={(v) => setP({ ...p, [key]: v })} fields={fields} /></label>
  );
  const multiFields = (key: string, label: string) => (
    <div className="field"><span>{label}</span>
      <div className="row">{fields.map((f) => (
        <label key={f.key} className="checkbox"><input type="checkbox" checked={(p[key] ?? []).includes(f.key)}
          onChange={(e) => setP({ ...p, [key]: e.target.checked ? [...(p[key] ?? []), f.key] : (p[key] ?? []).filter((x: string) => x !== f.key) })} /> {f.label}</label>
      ))}</div>
    </div>
  );

  return (
    <Modal title={initial ? `Editar regra (gera a versão ${initial.version + 1})` : "Nova regra de validação"} onClose={onClose} actions={
      <>
        <button className="btn" onClick={onClose}>Cancelar</button>
        <button className="btn" onClick={check}>Validar parâmetros</button>
        <button className="btn primary" onClick={save} disabled={busy || name.trim().length < 2}>{busy ? "Salvando…" : "Salvar"}</button>
      </>
    }>
      <ErrorAlert error={error} />
      {checked && !error && <Alert kind="success">Parâmetros válidos.</Alert>}
      <div className="stack">
        <div className="form-grid">
          <label className="field">Nome<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="field">Tipo
            <select value={ruleType} disabled={!!initial} onChange={(e) => { setRuleType(e.target.value); setP({ field: fields[0]?.key }); setChecked(false); }}>
              {catalog.map((c) => <option key={c.type} value={c.type}>{c.label}</option>)}
            </select>
          </label>
          <label className="field">Severidade
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              <option value="error">Erro</option><option value="warning">Alerta</option><option value="info">Informação</option>
            </select>
          </label>
          <label className="field">Situação
            <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="active">Ativa</option><option value="inactive">Desativada</option></select>
          </label>
          {!initial && (
            <label className="field">Aplicar a
              <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
                <option value="">Todas as empresas</option>
                {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
          )}
        </div>
        {meta && <p className="muted small" style={{ margin: 0 }}>{meta.description}</p>}

        {["required", "completeness", "data_type", "format", "range", "valid_date", "allowed_values", "regex", "cross_file"].includes(ruleType) && (
          <div className="form-grid">
            {field()}
            {ruleType === "data_type" && <label className="field">Tipo esperado
              <select value={p.type ?? "decimal"} onChange={(e) => setP({ ...p, type: e.target.value })}>{Object.entries(TYPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>}
            {ruleType === "format" && <label className="field">Formato
              <select value={p.format ?? "cnpj"} onChange={(e) => setP({ ...p, format: e.target.value })}>{Object.entries(FORMATS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>}
            {ruleType === "range" && <>
              <label className="field">Mínimo<input value={p.min ?? ""} onChange={(e) => setP({ ...p, min: e.target.value || undefined })} /></label>
              <label className="field">Máximo<input value={p.max ?? ""} onChange={(e) => setP({ ...p, max: e.target.value || undefined })} /></label>
              <label className="checkbox"><input type="checkbox" checked={!!p.exclusive_min} onChange={(e) => setP({ ...p, exclusive_min: e.target.checked })} /> mínimo exclusivo</label>
            </>}
            {ruleType === "valid_date" && <>
              <label className="field">Data mínima<input type="date" value={p.min_date ?? ""} onChange={(e) => setP({ ...p, min_date: e.target.value || undefined })} /></label>
              <label className="field">Data máxima<input type="date" value={p.max_date ?? ""} onChange={(e) => setP({ ...p, max_date: e.target.value || undefined })} /></label>
              <label className="checkbox"><input type="checkbox" checked={!!p.not_in_future} onChange={(e) => setP({ ...p, not_in_future: e.target.checked })} /> não pode ser futura</label>
            </>}
            {ruleType === "allowed_values" && <label className="field">Valores permitidos (separados por ;)
              <input value={Array.isArray(p.values) ? p.values.join("; ") : p.values ?? ""} onChange={(e) => setP({ ...p, values: e.target.value })} /></label>}
            {ruleType === "regex" && <>
              <label className="field">Padrão (expressão regular restrita)<input className="mono" value={p.pattern ?? ""} onChange={(e) => setP({ ...p, pattern: e.target.value })} /></label>
              <label className="checkbox"><input type="checkbox" checked={p.must_match ?? true} onChange={(e) => setP({ ...p, must_match: e.target.checked })} /> o valor deve corresponder</label>
            </>}
            {ruleType === "completeness" && <label className="field">Mínimo preenchido (0 a 1)
              <input type="number" step="0.01" min="0" max="1" value={p.min_ratio ?? 0.95} onChange={(e) => setP({ ...p, min_ratio: Number(e.target.value) })} /></label>}
            {ruleType === "cross_file" && <>
              <label className="field">Arquivo de referência
                <select value={p.reference_file_id ?? ""} onChange={(e) => setP({ ...p, reference_file_id: e.target.value })}>
                  <option value="">Selecione…</option>{files.map((f) => <option key={f.id} value={f.id}>{f.original_filename}</option>)}</select></label>
              <label className="field">Coluna de referência
                <select value={p.reference_column ?? ""} onChange={(e) => setP({ ...p, reference_column: e.target.value })}>
                  <option value="">Selecione…</option>{refColumns.map((c) => <option key={c}>{c}</option>)}</select></label>
            </>}
          </div>
        )}
        {["duplicate", "unique_key"].includes(ruleType) && multiFields("fields", "Campos da combinação")}
        {ruleType === "total_consistency" && (
          <div className="stack">
            <label className="field">Modo
              <select value={p.mode ?? "row"} onChange={(e) => setP({ ...p, mode: e.target.value })}>
                <option value="row">Na mesma linha: total = soma de campos</option>
                <option value="group">Por grupo: soma dos itens = total do grupo</option>
              </select></label>
            <div className="form-grid">
              {field("total_field", "Campo total")}
              {p.mode === "group" && field("item_field", "Campo do item")}
              <label className="field">Tolerância<input value={p.tolerance ?? "0.01"} onChange={(e) => setP({ ...p, tolerance: e.target.value })} /></label>
            </div>
            {(p.mode ?? "row") === "row" ? multiFields("item_fields", "Campos somados") : multiFields("group_by", "Agrupar por")}
          </div>
        )}
        {ruleType === "dependency" && <>
          <ConditionBuilder label="Quando" group={when} setGroup={setWhen} fields={fields} />
          <ConditionBuilder label="Então deve valer" group={then} setGroup={setThen} fields={fields} />
        </>}
        {ruleType === "custom" && <>
          <ConditionBuilder label="Aplicar somente quando (opcional)" group={when} setGroup={setWhen} fields={fields} />
          <ConditionBuilder label="Condição que deve ser verdadeira" group={then} setGroup={setThen} fields={fields} />
        </>}
        {!["dependency", "custom"].includes(ruleType) && (
          <details>
            <summary className="muted">Condição de aplicação (opcional)</summary>
            <ConditionBuilder label="Aplicar a regra somente quando" group={applies} setGroup={setApplies} fields={fields} />
          </details>
        )}
        <label className="field">Descrição<input value={description} onChange={(e) => setDescription(e.target.value)} /></label>
        <label className="field">Mensagem personalizada (opcional)<input value={message} onChange={(e) => setMessage(e.target.value)} /></label>
      </div>
    </Modal>
  );
}
