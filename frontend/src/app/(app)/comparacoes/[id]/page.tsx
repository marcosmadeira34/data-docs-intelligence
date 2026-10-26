"use client";

import { useEffect, useState } from "react";
import { Alert, Badge, Empty, ErrorAlert, PageHeader, Pagination, Spinner, Stat, useAsync } from "@/components/ui";
import { api, downloadUrl } from "@/lib/api";
import { CATEGORY, ERROR_KIND, JOB_STATUS, fmtDateTime, fmtNumber } from "@/lib/format";

const LIMIT = 50;

export default function ComparisonDetailPage({ params }: { params: { id: string } }) {
  const cmp = useAsync(() => api<any>(`/comparisons/${params.id}`), [params.id]);
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const done = cmp.data && !["queued", "running"].includes(cmp.data.status);
  const results = useAsync(
    () => (done ? api<{ items: any[]; total: number }>(`/comparisons/${params.id}/results`, { query: { category, limit: LIMIT, offset } }) : Promise.resolve(null)),
    [params.id, done, category, offset]);

  const setCmp = cmp.setData;
  const running = !!cmp.data && !done;
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => setCmp(await api(`/comparisons/${params.id}`)), 2000);
    return () => clearInterval(t);
  }, [running, params.id, setCmp]);

  if (cmp.error) return <ErrorAlert error={cmp.error} />;
  if (!cmp.data) return <Spinner />;
  const c = cmp.data;
  const s = c.summary ?? {};
  const snap = c.input_snapshot ?? {};

  return (
    <>
      <PageHeader title={c.name || "Comparação"}
        subtitle={<>A: {snap.a?.file_name} · B: {snap.b?.file_name} · {fmtDateTime(c.created_at)} · <Badge kind={c.status}>{JOB_STATUS[c.status]}</Badge></>}
        actions={c.status === "succeeded" && <a className="btn" href={downloadUrl(`/comparisons/${c.id}/export.csv`)}>Exportar relatório CSV</a>} />
      {!done && <div className="card"><Spinner label="Comparando arquivos…" /></div>}
      {c.status === "failed" && <Alert kind="error" title={ERROR_KIND[c.error_kind] ?? "Falha"}>{c.failure_reason}</Alert>}
      {c.status === "succeeded" && (
        <>
          <div className="grid cols-4" style={{ marginBottom: 16 }}>
            <Stat label="Registros em A / B" value={`${fmtNumber(s.rows_a)} / ${fmtNumber(s.rows_b)}`} />
            <Stat label="Correspondentes sem divergência" value={fmtNumber(s.match)} />
            <Stat label="Correspondentes com divergência" value={fmtNumber(s.mismatch)} />
            <Stat label="Somente em A / somente em B" value={`${fmtNumber(s.only_a)} / ${fmtNumber(s.only_b)}`} />
            <Stat label="Chaves duplicadas (A / B)" value={`${fmtNumber(s.duplicate_key_a)} / ${fmtNumber(s.duplicate_key_b)}`} hint="correspondência ambígua" />
            <Stat label="Sem chave (A / B)" value={`${fmtNumber(s.missing_key_a)} / ${fmtNumber(s.missing_key_b)}`} hint="não comparáveis com segurança" />
          </div>
          {s.field_divergences && Object.keys(s.field_divergences).length > 0 && (
            <div className="card"><h3>Divergências por campo</h3>
              <ul style={{ margin: 0 }}>{Object.entries(s.field_divergences).map(([k, n]) => <li key={k}>{k}: {fmtNumber(n as number)}</li>)}</ul>
            </div>
          )}
          {c.results_truncated && <Alert kind="warning">O resultado excedeu o limite armazenado; contagens completas, detalhes parciais.</Alert>}
          <div className="card flush">
            <div className="card-header" style={{ padding: "14px 16px 0" }}>
              <h2>Detalhes</h2>
              <select value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0); }} aria-label="Categoria">
                <option value="">Todas as categorias</option>
                {Object.entries(CATEGORY).filter(([k]) => k !== "match").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <ErrorAlert error={results.error} />
            {results.data && results.data.items.length === 0 ? <Empty>Nada nesta categoria.</Empty> : results.data && (
              <div className="table-wrap"><table>
                <thead><tr><th>Categoria</th><th>Chave</th><th className="right">Linha A</th><th className="right">Linha B</th><th>Diferenças</th></tr></thead>
                <tbody>{results.data.items.map((r) => (
                  <tr key={r.id}>
                    <td><Badge kind={r.category === "mismatch" ? "warning" : r.category.startsWith("only") ? "info" : "error"}>{CATEGORY[r.category]}</Badge></td>
                    <td className="mono small">{r.key_value ?? "—"}</td>
                    <td className="num">{r.row_a ?? "—"}</td>
                    <td className="num">{r.row_b ?? "—"}</td>
                    <td className="small">
                      {r.differences.map((d: any, i: number) => (
                        <div key={i}><strong>{d.column_a} × {d.column_b}</strong>: {d.value_a || "(vazio)"} → {d.value_b || "(vazio)"}
                          <span className="muted"> · {d.reason}{d.delta ? ` (Δ ${d.delta})` : ""}{d.delta_days ? ` (Δ ${d.delta_days} dias)` : ""}</span></div>
                      ))}
                      {r.note && <div className="muted">{r.note}</div>}
                    </td>
                  </tr>
                ))}</tbody>
              </table>
              <Pagination total={results.data.total} limit={LIMIT} offset={offset} onChange={setOffset} /></div>
            )}
          </div>
        </>
      )}
    </>
  );
}
