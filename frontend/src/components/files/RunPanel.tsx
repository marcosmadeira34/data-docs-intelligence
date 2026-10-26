"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, ErrorAlert, Spinner, useAsync } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { COMPAT, SEVERITY } from "@/lib/format";
import { Compatibility, FileAsset, Profile, Rule } from "@/lib/types";

export function RunPanel({ file, profileId, canRun }: { file: FileAsset; profileId: string; canRun: boolean }) {
  const router = useRouter();
  const [selectedProfile, setSelectedProfile] = useState(profileId);
  const [selectedRules, setSelectedRules] = useState<Set<string>>(new Set());
  const [autoTypes, setAutoTypes] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [compat, setCompat] = useState<Compatibility | null>(null);

  useEffect(() => setSelectedProfile(profileId), [profileId]);
  const profiles = useAsync(() => api<{ items: Profile[] }>("/profiles", { query: { limit: 200 } }), [profileId]);
  const rules = useAsync(() => api<{ items: Rule[] }>("/validation-rules", { query: { limit: 200, client_id: file.client_account_id } }), [file.id]);

  const usable = useMemo(() => (profiles.data?.items ?? []).filter((p) => p.current_version &&
    (!p.client_account_id || p.client_account_id === file.client_account_id)), [profiles.data, file]);

  useEffect(() => {
    if (!rules.data) return;
    // Pré-seleção: regras ativas da organização (globais exigem escolha explícita)
    setSelectedRules(new Set(rules.data.items.filter((r) => r.status === "active" && !r.is_global &&
      (!r.profile_id || r.profile_id === selectedProfile)).map((r) => r.id)));
  }, [rules.data, selectedProfile]);

  useEffect(() => {
    setCompat(null);
    if (!selectedProfile) return;
    api<Compatibility>(`/profiles/${selectedProfile}/compatibility`, { query: { file_id: file.id } }).then(setCompat).catch(() => setCompat(null));
  }, [selectedProfile, file.id]);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const job = await api("/jobs", { method: "POST", body: { file_id: file.id, profile_id: selectedProfile, rule_ids: Array.from(selectedRules),
        auto_type_checks: autoTypes }, headers: { "Idempotency-Key": `${file.id}-${selectedProfile}-${Date.now()}` } });
      router.push(`/execucoes/${job.id}`);
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.code === "structure_review_required") setCompat(e.details as Compatibility);
    } finally {
      setBusy(false);
    }
  };

  if (profiles.loading && !profiles.data) return <Spinner />;
  const activeRules = (rules.data?.items ?? []).filter((r) => r.status === "active");

  return (
    <div className="stack">
      <ErrorAlert error={error ?? profiles.error ?? rules.error} />
      <div className="card">
        <h2>Perfil de processamento</h2>
        {usable.length === 0 ? (
          <Alert kind="info">Nenhum perfil aprovado disponível. Aprove um mapeamento na aba “Mapeamento”.</Alert>
        ) : (
          <label className="field" style={{ maxWidth: 480 }}>Perfil aprovado
            <select value={selectedProfile} onChange={(e) => setSelectedProfile(e.target.value)}>
              <option value="">Selecione…</option>
              {usable.map((p) => <option key={p.id} value={p.id}>{p.name} (v{p.current_version?.version}){p.client_name ? "" : " — organização"}</option>)}
            </select>
          </label>
        )}
        {compat && (
          <div style={{ marginTop: 12 }}>
            <Badge kind={compat.status}>{COMPAT[compat.status]}</Badge>
            {compat.messages.length > 0 && <ul className="small">{compat.messages.map((m, i) => <li key={i}>{m}</li>)}</ul>}
            {compat.requires_review && <Alert kind="warning">A estrutura mudou. Revise o mapeamento e crie uma nova versão do perfil antes de processar.</Alert>}
          </div>
        )}
      </div>

      <div className="card flush">
        <div className="card-header" style={{ padding: "14px 16px 0" }}>
          <h2>Regras a aplicar</h2>
          <label className="checkbox"><input type="checkbox" checked={autoTypes} onChange={(e) => setAutoTypes(e.target.checked)} />
            verificar tipos dos campos mapeados automaticamente</label>
        </div>
        {activeRules.length === 0 ? <div className="empty">Nenhuma regra ativa. Campos obrigatórios e tipos do mapeamento ainda serão verificados.</div> : (
          <div className="table-wrap"><table>
            <thead><tr><th></th><th>Regra</th><th>Tipo</th><th>Severidade</th><th>Origem</th></tr></thead>
            <tbody>{activeRules.map((r) => (
              <tr key={r.id}>
                <td><input type="checkbox" aria-label={`Aplicar ${r.name}`} checked={selectedRules.has(r.id)} onChange={(e) => {
                  const next = new Set(selectedRules);
                  e.target.checked ? next.add(r.id) : next.delete(r.id);
                  setSelectedRules(next);
                }} /></td>
                <td>{r.name} <span className="muted small">v{r.version}</span></td>
                <td className="small">{r.rule_type}</td>
                <td><Badge kind={r.severity}>{SEVERITY[r.severity]}</Badge></td>
                <td className="small">{r.is_global ? "Catálogo global" : "Organização"}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {canRun && (
        <div className="row">
          <button className="btn primary" onClick={run} disabled={busy || !selectedProfile || file.status === "deleted" || !!compat?.requires_review}>
            {busy ? "Iniciando…" : "Executar validação"}
          </button>
          <span className="muted small">Arquivos pequenos são processados na hora; maiores entram na fila do worker.</span>
        </div>
      )}
    </div>
  );
}
