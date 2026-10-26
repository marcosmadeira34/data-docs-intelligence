"use client";

import { useState } from "react";
import { RuleForm } from "@/components/rules/RuleForm";
import { Badge, Empty, ErrorAlert, Modal, PageHeader, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { SEVERITY, fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { CanonicalField, Rule, RuleType } from "@/lib/types";

export default function RulesPage() {
  const { can } = useSession();
  const [editing, setEditing] = useState<Rule | "new" | null>(null);
  const [history, setHistory] = useState<Rule | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const catalog = useAsync(() => api<{ rule_types: RuleType[]; canonical_fields: CanonicalField[] }>("/validation-rules/catalog"), []);
  const rules = useAsync(() => api<{ items: Rule[]; total: number }>("/validation-rules", { query: { limit: 200 } }), []);
  const hist = useAsync(() => (history ? api<Rule & { history: Rule[] }>(`/validation-rules/${history.id}`) : Promise.resolve(null)), [history?.id]);
  const typeLabel = (t: string) => catalog.data?.rule_types.find((c) => c.type === t)?.label ?? t;
  const fieldLabel = (k?: string) => catalog.data?.canonical_fields.find((f) => f.key === k)?.label ?? k;

  const describe = (r: Rule) => {
    const p = r.params;
    if (p.field) return fieldLabel(p.field);
    if (p.fields) return p.fields.map(fieldLabel).join(" + ");
    if (p.total_field) return `${fieldLabel(p.total_field)} (${p.mode})`;
    return "condições";
  };

  const clone = async (r: Rule) => {
    setActionError(null);
    try {
      await api(`/validation-rules/${r.id}/clone`, { method: "POST" });
      rules.reload();
    } catch (e) {
      setActionError(e);
    }
  };

  const org = rules.data?.items.filter((r) => !r.is_global) ?? [];
  const global = rules.data?.items.filter((r) => r.is_global) ?? [];

  const table = (items: Rule[], isGlobal: boolean) => (
    <div className="table-wrap"><table>
      <thead><tr><th>Regra</th><th>Tipo</th><th>Campo(s)</th><th>Severidade</th><th>Situação</th><th>Versão</th><th></th></tr></thead>
      <tbody>{items.map((r) => (
        <tr key={r.id}>
          <td>{r.name}{r.description && <div className="small muted">{r.description}</div>}</td>
          <td className="small">{typeLabel(r.rule_type)}</td>
          <td className="small">{describe(r)}</td>
          <td><Badge kind={r.severity}>{SEVERITY[r.severity]}</Badge></td>
          <td><Badge kind={r.status === "active" ? "active" : ""}>{r.status === "active" ? "Ativa" : "Desativada"}</Badge></td>
          <td className="small"><button className="btn small" onClick={() => setHistory(r)}>v{r.version} · histórico</button></td>
          <td className="nowrap">{can("analyst") && (isGlobal
            ? <button className="btn small" onClick={() => clone(r)}>Duplicar para a organização</button>
            : <button className="btn small" onClick={() => setEditing(r)}>Editar</button>)}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );

  return (
    <>
      <PageHeader title="Regras de validação" subtitle="Regras declarativas sobre os campos padronizados. Cada alteração gera uma nova versão; execuções registram a versão usada."
        actions={can("analyst") && catalog.data && <button className="btn primary" onClick={() => setEditing("new")}>Nova regra</button>} />
      <ErrorAlert error={rules.error ?? catalog.error ?? actionError} />
      {rules.loading && !rules.data ? <Spinner /> : (
        <>
          <div className="card flush">
            <div className="card-header" style={{ padding: "14px 16px 0" }}><h2>Regras da organização</h2></div>
            {org.length ? table(org, false) : <Empty>Nenhuma regra própria. Crie uma ou duplique uma regra do catálogo global.</Empty>}
          </div>
          <div className="card flush">
            <div className="card-header" style={{ padding: "14px 16px 0" }}>
              <div><h2>Catálogo global</h2><p className="muted small" style={{ margin: 0 }}>Mantido pela plataforma; somente leitura. Selecione-as explicitamente na execução ou duplique para personalizar.</p></div>
            </div>
            {table(global, true)}
          </div>
        </>
      )}
      {editing && catalog.data && (
        <RuleForm initial={editing === "new" ? undefined : editing} catalog={catalog.data.rule_types} fields={catalog.data.canonical_fields}
          onSaved={rules.reload} onClose={() => setEditing(null)} />
      )}
      {history && (
        <Modal title={`Histórico — ${history.name}`} onClose={() => setHistory(null)} actions={<button className="btn" onClick={() => setHistory(null)}>Fechar</button>}>
          {hist.data ? (
            <table>
              <thead><tr><th>Versão</th><th>Severidade</th><th>Situação</th><th>Parâmetros</th><th>Data</th></tr></thead>
              <tbody>{hist.data.history.map((h) => (
                <tr key={h.id}><td>v{h.version}{h.is_current && " (atual)"}</td><td>{SEVERITY[h.severity]}</td><td>{h.status}</td>
                  <td className="mono small">{JSON.stringify(h.params)}</td><td className="nowrap">{fmtDateTime(h.created_at)}</td></tr>
              ))}</tbody>
            </table>
          ) : <Spinner />}
        </Modal>
      )}
    </>
  );
}
