"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert, Badge, Empty, ErrorAlert, PageHeader, Pagination, Spinner, Stat, useAsync } from "@/components/ui";
import { api, downloadUrl } from "@/lib/api";
import { ERROR_KIND, JOB_STATUS, REVIEW, SEVERITY, fmtDateTime, fmtNumber } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Job } from "@/lib/types";

type Finding = {
  id: number; rule_key: string; rule_version: number; rule_type: string; rule_name: string | null; severity: string;
  row_number: number | null; record_key: string | null; field: string | null; observed_value: string | null; message: string;
  evidence: Record<string, unknown>; review_status: string;
};
type FindingPage = { items: Finding[]; total: number; facets: Record<string, Record<string, number>> };
const LIMIT = 50;

export default function JobDetailPage({ params }: { params: { id: string } }) {
  const { can } = useSession();
  const router = useRouter();
  const job = useAsync(() => api<Job>(`/jobs/${params.id}`), [params.id]);
  const [filters, setFilters] = useState({ severity: "", rule_key: "", field: "", review_status: "", q: "" });
  const [offset, setOffset] = useState(0);
  const [showEvidence, setShowEvidence] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const done = job.data && !["queued", "running"].includes(job.data.status);
  const findings = useAsync(
    () => (done ? api<FindingPage>(`/jobs/${params.id}/findings`, { query: { ...filters, limit: LIMIT, offset } }) : Promise.resolve(null)),
    [params.id, done, JSON.stringify(filters), offset]);
  const report = useAsync(() => (showEvidence ? api(`/jobs/${params.id}/report`) : Promise.resolve(null)), [showEvidence, params.id]);

  // Atualiza o estado enquanto a execução estiver em andamento (progresso real informado pelo backend).
  const setJob = job.setData;
  const running = !!job.data && !done;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => setJob(await api<Job>(`/jobs/${params.id}`)), 2000);
    return () => clearInterval(t);
  }, [running, params.id, setJob]);

  if (job.error) return <ErrorAlert error={job.error} />;
  if (!job.data) return <Spinner />;
  const j = job.data;
  const snap = j.input_snapshot ?? {};
  const setFilter = (k: keyof typeof filters, v: string) => { setFilters({ ...filters, [k]: v }); setOffset(0); };

  const review = async (f: Finding, status: string) => {
    await api(`/jobs/${j.id}/findings/${f.id}`, { method: "PATCH", body: { review_status: status } });
    findings.reload();
  };
  const reprocess = async () => {
    setActionError(null);
    try {
      const n = await api<Job>(`/jobs/${j.id}/reprocess`, { method: "POST" });
      router.push(`/execucoes/${n.id}`);
    } catch (e) {
      setActionError(e);
    }
  };

  return (
    <>
      <PageHeader title={`Execução — ${snap.file_name ?? ""}`}
        subtitle={<>Perfil {snap.profile_name} v{snap.profile_version} · iniciada em {fmtDateTime(j.created_at)} ·{" "}
          <Badge kind={j.status}>{JOB_STATUS[j.status]}</Badge></>}
        actions={<>
          {done && j.status === "succeeded" && <a className="btn" href={downloadUrl(`/jobs/${j.id}/findings/export.csv`, filters)}>Exportar CSV</a>}
          <button className="btn" onClick={() => setShowEvidence(!showEvidence)}>{showEvidence ? "Ocultar evidências" : "Evidências da execução"}</button>
          {can("analyst") && done && <button className="btn" onClick={reprocess}>Reprocessar</button>}
          {can("analyst") && j.status === "queued" && <button className="btn danger" onClick={async () => job.setData(await api(`/jobs/${j.id}/cancel`, { method: "POST" }))}>Cancelar</button>}
        </>} />
      <ErrorAlert error={actionError} />
      {!done && (
        <div className="card">
          <Spinner label={j.status === "queued" ? "Na fila de processamento…" : `Processando… ${fmtNumber(j.records_read)} registros lidos até agora`} />
        </div>
      )}
      {j.status === "failed" && (
        <Alert kind="error" title={`${ERROR_KIND[j.error_kind ?? ""] ?? "Falha"}`}>
          {j.failure_reason} (tentativas: {j.attempts}/{j.max_attempts})
        </Alert>
      )}
      {j.status === "queued" && j.failure_reason && <Alert kind="warning">{j.failure_reason}</Alert>}

      {j.status === "succeeded" && (
        <>
          <div className="grid cols-4" style={{ marginBottom: 16 }}>
            <Stat label="Registros analisados" value={fmtNumber(j.records_read)} />
            <Stat label="Erros" value={fmtNumber(j.error_count)} />
            <Stat label="Alertas" value={fmtNumber(j.warning_count)} />
            <Stat label="Informações" value={fmtNumber(j.info_count)} hint={j.summary?.duration_seconds !== undefined ? `processado em ${j.summary.duration_seconds}s` : undefined} />
          </div>
          {j.error_count + j.warning_count === 0 && <Alert kind="success">Nenhum erro ou alerta encontrado pelas regras aplicadas.</Alert>}
          {j.summary?.truncated_rules?.length > 0 && (
            <Alert kind="warning">Algumas regras geraram mais achados do que o limite armazenado; as contagens acima são completas, a tabela mostra os primeiros.</Alert>
          )}
          {j.summary?.rules?.some((r: any) => r.skipped_reason) && (
            <Alert kind="info" title="Regras não aplicadas">
              <ul>{j.summary.rules.filter((r: any) => r.skipped_reason).map((r: any) => <li key={r.rule_key}>{r.rule_key}: {r.skipped_reason}</li>)}</ul>
            </Alert>
          )}
        </>
      )}

      {showEvidence && report.data && (
        <div className="card">
          <h2>Evidências de reprodutibilidade</h2>
          <dl className="kv">
            <dt>Execução</dt><dd className="mono">{report.data.job_id}</dd>
            <dt>Arquivo</dt><dd>{snap.file_name} · <Link href={`/arquivos/${snap.file_id}`}>abrir</Link></dd>
            <dt>SHA-256</dt><dd className="mono">{snap.sha256}</dd>
            <dt>Leitura</dt><dd className="mono">{JSON.stringify(snap.read_options)}</dd>
            <dt>Perfil</dt><dd>{snap.profile_name} — versão {snap.profile_version} ({snap.compatibility})</dd>
            <dt>Período</dt><dd>{fmtDateTime(report.data.started_at)} → {fmtDateTime(report.data.finished_at)} · tentativas: {report.data.attempts}</dd>
            <dt>Regras</dt><dd>{report.data.rules.map((r: any) => `${r.rule_key} v${r.version} (${r.severity})`).join(", ")}</dd>
          </dl>
        </div>
      )}

      {done && j.status === "succeeded" && (
        <div className="card flush">
          <div className="card-header" style={{ padding: "14px 16px 0" }}><h2>Inconsistências</h2></div>
          <div className="row" style={{ padding: "0 16px 12px" }}>
            <select value={filters.severity} onChange={(e) => setFilter("severity", e.target.value)} aria-label="Severidade">
              <option value="">Todas as severidades</option>
              {Object.entries(findings.data?.facets.severity ?? {}).map(([k, n]) => <option key={k} value={k}>{SEVERITY[k]} ({n})</option>)}
            </select>
            <select value={filters.rule_key} onChange={(e) => setFilter("rule_key", e.target.value)} aria-label="Regra">
              <option value="">Todas as regras</option>
              {Object.entries(findings.data?.facets.rule_key ?? {}).map(([k, n]) => <option key={k} value={k}>{k} ({n})</option>)}
            </select>
            <select value={filters.field} onChange={(e) => setFilter("field", e.target.value)} aria-label="Campo">
              <option value="">Todos os campos</option>
              {Object.entries(findings.data?.facets.field ?? {}).map(([k, n]) => <option key={k} value={k}>{k} ({n})</option>)}
            </select>
            <select value={filters.review_status} onChange={(e) => setFilter("review_status", e.target.value)} aria-label="Revisão">
              <option value="">Qualquer revisão</option>
              {Object.entries(REVIEW).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <input placeholder="Buscar chave do registro" value={filters.q} onChange={(e) => setFilter("q", e.target.value)} />
          </div>
          <ErrorAlert error={findings.error} />
          {findings.loading && !findings.data ? <div className="empty"><Spinner /></div> : findings.data && findings.data.items.length === 0 ? (
            <Empty>Nenhuma inconsistência com os filtros selecionados.</Empty>
          ) : findings.data && (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Linha</th><th>Registro</th><th>Severidade</th><th>Regra</th><th>Campo</th><th>Valor</th><th>Mensagem</th><th>Revisão</th></tr></thead>
                <tbody>
                  {findings.data.items.map((f) => (
                    <tr key={f.id}>
                      <td className="num">{f.row_number ?? "arquivo"}</td>
                      <td className="small">{f.record_key ?? "—"}</td>
                      <td><Badge kind={f.severity}>{SEVERITY[f.severity]}</Badge></td>
                      <td className="small">{f.rule_name || f.rule_key}<div className="muted">v{f.rule_version}</div></td>
                      <td className="small">{f.field ?? "—"}</td>
                      <td className="small mono">{f.observed_value ?? "—"}</td>
                      <td className="small">{f.message}
                        {Object.keys(f.evidence ?? {}).length > 0 && <div className="muted mono" style={{ fontSize: 11.5 }}>{JSON.stringify(f.evidence)}</div>}</td>
                      <td>
                        {can("analyst") ? (
                          <select value={f.review_status} onChange={(e) => review(f, e.target.value)} aria-label="Status de revisão">
                            {Object.entries(REVIEW).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        ) : REVIEW[f.review_status]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <Pagination total={findings.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
            </div>
          )}
        </div>
      )}
    </>
  );
}
