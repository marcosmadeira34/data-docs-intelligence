"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Empty, ErrorAlert, PageHeader, Pagination, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { ERROR_KIND, JOB_STATUS, fmtDateTime, fmtNumber } from "@/lib/format";
import { Job } from "@/lib/types";

export default function JobsPage() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const jobs = useAsync(() => api<{ items: Job[]; total: number }>("/jobs", { query: { status, limit: 50, offset } }), [status, offset]);
  const clients = useAsync(() => api<{ items: { id: string; name: string }[] }>("/clients", { query: { limit: 200 } }), []);
  const clientName = (id: string) => clients.data?.items.find((c) => c.id === id)?.name ?? "—";

  return (
    <>
      <PageHeader title="Execuções" subtitle="Histórico de validações com arquivo, perfil e regras utilizadas."
        actions={<button className="btn" onClick={jobs.reload}>Atualizar</button>} />
      <div className="card row">
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} aria-label="Situação">
          <option value="">Todas as situações</option>
          {Object.entries(JOB_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <ErrorAlert error={jobs.error} />
      <div className="card flush">
        {jobs.loading && !jobs.data ? <div className="empty"><Spinner /></div> : jobs.data && jobs.data.items.length === 0 ? (
          <Empty>Nenhuma execução. Abra um <Link href="/arquivos">arquivo</Link> para executar uma validação.</Empty>
        ) : jobs.data && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Arquivo</th><th>Empresa</th><th>Perfil</th><th>Situação</th><th className="right">Registros</th>
                <th className="right">Erros</th><th className="right">Alertas</th><th>Início</th></tr></thead>
              <tbody>
                {jobs.data.items.map((j) => (
                  <tr key={j.id}>
                    <td><Link href={`/execucoes/${j.id}`}>{j.input_snapshot?.file_name ?? j.id.slice(0, 8)}</Link></td>
                    <td>{clientName(j.client_account_id)}</td>
                    <td className="small">{j.input_snapshot?.profile_name} v{j.input_snapshot?.profile_version}</td>
                    <td><Badge kind={j.status}>{JOB_STATUS[j.status]}</Badge>{j.error_kind && <div className="small muted">{ERROR_KIND[j.error_kind]}</div>}</td>
                    <td className="num">{fmtNumber(j.records_read)}</td>
                    <td className="num">{fmtNumber(j.error_count)}</td>
                    <td className="num">{fmtNumber(j.warning_count)}</td>
                    <td className="nowrap">{fmtDateTime(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination total={jobs.data.total} limit={50} offset={offset} onChange={setOffset} />
          </div>
        )}
      </div>
    </>
  );
}
