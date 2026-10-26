"use client";

import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, ErrorAlert, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { COMPAT, INFERRED_TYPE } from "@/lib/format";
import { CanonicalField, FileAsset, MappingEntry, ProfileMatch, Suggestion } from "@/lib/types";

type SuggestResponse = { provider: string; confirmation_threshold: number; suggestions: Suggestion[]; profile_matches: ProfileMatch[] };
const TRANSFORMS: Record<string, string> = { trim: "remover espaços", upper: "maiúsculas", digits_only: "só dígitos", abs: "valor absoluto", negate: "inverter sinal" };

function toEntry(s: Suggestion): MappingEntry {
  return {
    source_column: s.source_column, target_field: s.target_field,
    status: !s.target_field ? "ignored" : s.requires_confirmation ? "suggested" : "approved",
    confidence: s.confidence, rationale: s.rationale, transforms: [], required: false,
    number_style: s.number_style ?? "auto", date_format: s.date_format && s.date_format !== "dd/mm/yyyy" ? s.date_format : null,
    source: s.source,
  };
}

export function MappingPanel({ file, canEdit, onUseProfile }: { file: FileAsset; canEdit: boolean; onUseProfile: (profileId: string) => void }) {
  const [data, setData] = useState<SuggestResponse | null>(null);
  const [fields, setFields] = useState<CanonicalField[]>([]);
  const [entries, setEntries] = useState<MappingEntry[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [mode, setMode] = useState<"new" | "version">("new");
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"client" | "org">("client");
  const [targetProfile, setTargetProfile] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<SuggestResponse>(`/files/${file.id}/mapping`, { method: "POST" }), api("/validation-rules/catalog")])
      .then(([s, cat]) => {
        setData(s);
        setFields(cat.canonical_fields);
        setEntries(s.suggestions.map(toEntry));
        const review = s.profile_matches.find((m) => m.compatibility.requires_review);
        if (review) {
          setMode("version");
          setTargetProfile(review.profile_id);
        }
      })
      .catch(setError);
  }, [file.id]);

  const byColumn = useMemo(() => Object.fromEntries((data?.suggestions ?? []).map((s) => [s.source_column, s])), [data]);
  const pending = entries.filter((e) => e.status === "suggested").length;
  const duplicateTargets = useMemo(() => {
    const seen: Record<string, number> = {};
    entries.forEach((e) => e.target_field && e.status !== "ignored" && (seen[e.target_field] = (seen[e.target_field] ?? 0) + 1));
    return new Set(Object.keys(seen).filter((k) => seen[k] > 1));
  }, [entries]);

  const update = (i: number, patch: Partial<MappingEntry>) => setEntries(entries.map((e, j) => (j === i ? { ...e, ...patch } : e)));

  const save = async () => {
    setBusy(true);
    setSaveError(null);
    setSaved(null);
    const payload = entries.map((e) => ({ ...e, target_field: e.status === "ignored" ? null : e.target_field }));
    const source = entries.some((e) => e.source === "ai") ? "ai" : "heuristic";
    try {
      let profileId: string;
      if (mode === "new") {
        const p = await api("/profiles", { method: "POST", body: {
          name, client_id: scope === "client" ? file.client_account_id : null, file_id: file.id, entries: payload, approve: true,
          suggestion_source: source } });
        profileId = p.id;
      } else {
        const p = await api(`/profiles/${targetProfile}/versions`, { method: "POST", body: {
          file_id: file.id, entries: payload, approve: true, change_note: note || null, suggestion_source: source } });
        profileId = p.id;
      }
      setSaved(profileId);
      onUseProfile(profileId);
    } catch (e) {
      setSaveError(e);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorAlert error={error} />;
  if (!data) return <Spinner label="Gerando sugestões de mapeamento…" />;

  return (
    <div className="stack">
      {data.profile_matches.length > 0 && (
        <div className="card">
          <h2>Perfis aprovados para comparar com este arquivo</h2>
          <div className="stack">
            {data.profile_matches.map((m) => (
              <div key={m.profile_id} className="row between" style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                <div>
                  <strong>{m.profile_name}</strong> <span className="muted small">v{m.version}</span>{" "}
                  <Badge kind={m.compatibility.status}>{COMPAT[m.compatibility.status]}</Badge>
                  {m.compatibility.messages.length > 0 && <ul className="small muted" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                    {m.compatibility.messages.map((msg, i) => <li key={i}>{msg}</li>)}</ul>}
                </div>
                {m.compatibility.requires_review ? (
                  canEdit && <button className="btn small" onClick={() => { setMode("version"); setTargetProfile(m.profile_id); }}>Revisar e criar nova versão</button>
                ) : (
                  <button className="btn primary small" onClick={() => onUseProfile(m.profile_id)}>Usar este perfil</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card flush">
        <div className="card-header" style={{ padding: "14px 16px 0" }}>
          <div>
            <h2>Mapeamento de colunas</h2>
            <p className="muted small" style={{ margin: 0 }}>
              Sugestões por {data.provider === "ai" ? "heurística + IA" : "heurística determinística"}. A confiança é uma pontuação,
              não uma probabilidade; sugestões abaixo de {Math.round(data.confirmation_threshold * 100)}% ou com alertas exigem confirmação.
            </p>
          </div>
          {canEdit && pending > 0 && (
            <button className="btn small" onClick={() => setEntries(entries.map((e) => (e.status === "suggested" && !byColumn[e.source_column]?.warnings.length
              ? { ...e, status: "approved" } : e)))}>Confirmar sugestões sem alertas</button>
          )}
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Coluna de origem</th><th>Campo de destino</th><th className="right">Confiança</th><th>Justificativa</th><th>Opções</th><th>Situação</th></tr></thead>
            <tbody>
              {entries.map((e, i) => {
                const s = byColumn[e.source_column];
                return (
                  <tr key={e.source_column}>
                    <td><strong>{e.source_column}</strong><div className="small muted">{INFERRED_TYPE[s?.inferred_type ?? ""] ?? s?.inferred_type}</div></td>
                    <td>
                      <select value={e.status === "ignored" ? "" : e.target_field ?? ""} disabled={!canEdit}
                        onChange={(ev) => update(i, ev.target.value ? { target_field: ev.target.value, status: "approved" } : { target_field: null, status: "ignored" })}>
                        <option value="">— ignorar coluna —</option>
                        {fields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                        {e.target_field?.startsWith("x_") && <option value={e.target_field}>{e.target_field}</option>}
                      </select>
                      {e.target_field && duplicateTargets.has(e.target_field) && <div className="small" style={{ color: "var(--danger)" }}>Campo usado por mais de uma coluna</div>}
                    </td>
                    <td className="num confidence">{s?.target_field ? `${Math.round(s.confidence * 100)}%` : "—"}</td>
                    <td className="small">
                      {s?.rationale}
                      {s?.warnings.map((w, k) => <div key={k} style={{ color: "var(--warning)" }}>⚠ {w}</div>)}
                      {s?.source === "ai" && <div><Badge kind="info">IA</Badge></div>}
                    </td>
                    <td className="small">
                      {e.status !== "ignored" && (
                        <div className="stack" style={{ gap: 4 }}>
                          <label className="checkbox"><input type="checkbox" checked={e.required} disabled={!canEdit}
                            onChange={(ev) => update(i, { required: ev.target.checked })} /> obrigatório</label>
                          <details>
                            <summary className="muted">transformações</summary>
                            {Object.entries(TRANSFORMS).map(([k, label]) => (
                              <label key={k} className="checkbox" style={{ display: "flex" }}>
                                <input type="checkbox" checked={e.transforms.includes(k)} disabled={!canEdit}
                                  onChange={(ev) => update(i, { transforms: ev.target.checked ? [...e.transforms, k] : e.transforms.filter((t) => t !== k) })} /> {label}
                              </label>
                            ))}
                          </details>
                        </div>
                      )}
                    </td>
                    <td>
                      {e.status === "ignored" ? <Badge>Ignorada</Badge> : (
                        <select value={e.status} disabled={!canEdit} onChange={(ev) => update(i, { status: ev.target.value as MappingEntry["status"] })}>
                          <option value="suggested">Pendente</option>
                          <option value="approved">Confirmada</option>
                        </select>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {canEdit && (
        <div className="card">
          <h2>Salvar mapeamento aprovado</h2>
          <ErrorAlert error={saveError} />
          {saved && <Alert kind="success">Perfil salvo e aprovado. Ele já está selecionado na aba "Executar validação".</Alert>}
          {pending > 0 && <Alert kind="warning">{pending} coluna(s) ainda pendente(s): confirme ou ignore antes de aprovar.</Alert>}
          <div className="row" style={{ marginBottom: 12 }}>
            <label className="checkbox"><input type="radio" checked={mode === "new"} onChange={() => setMode("new")} /> Novo perfil</label>
            <label className="checkbox"><input type="radio" checked={mode === "version"} onChange={() => setMode("version")}
              disabled={data.profile_matches.length === 0} /> Nova versão de perfil existente</label>
          </div>
          {mode === "new" ? (
            <div className="form-grid">
              <label className="field">Nome do perfil
                <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: Contas a pagar — ERP do cliente" />
              </label>
              <label className="field">Abrangência
                <select value={scope} onChange={(e) => setScope(e.target.value as "client" | "org")}>
                  <option value="client">Somente esta empresa</option>
                  <option value="org">Todas as empresas da organização</option>
                </select>
              </label>
            </div>
          ) : (
            <div className="form-grid">
              <label className="field">Perfil
                <select value={targetProfile} onChange={(e) => setTargetProfile(e.target.value)}>
                  <option value="">Selecione…</option>
                  {data.profile_matches.map((m) => <option key={m.profile_id} value={m.profile_id}>{m.profile_name} (v{m.version})</option>)}
                </select>
              </label>
              <label className="field">Motivo da alteração
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ex.: cliente renomeou a coluna Valor" />
              </label>
            </div>
          )}
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={save}
              disabled={busy || pending > 0 || duplicateTargets.size > 0 || (mode === "new" ? name.trim().length < 2 : !targetProfile)}>
              {busy ? "Salvando…" : "Aprovar e salvar"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
