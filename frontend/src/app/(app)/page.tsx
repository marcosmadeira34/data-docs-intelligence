"use client";

import Link from "next/link";
import { useState } from "react";
import { ErrorAlert, PageHeader, Spinner, Stat, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { AUDIT_ACTION, fmtDateTime, fmtNumber } from "@/lib/format";

type Dashboard = {
  period_days: number;
  clients_active: number;
  files_uploaded: number;
  jobs_succeeded: number;
  jobs_failed: number;
  jobs_pending: number;
  comparisons: number;
  records_processed: number;
  errors_found: number;
  warnings_found: number;
  recent_activity: { id: number; action: string; actor_name: string | null; created_at: string; entity_type: string }[];
};

export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const { data, error, loading } = useAsync(() => api<Dashboard>("/dashboard", { query: { days } }), [days]);

  return (
    <>
      <PageHeader title="Painel" subtitle="Indicadores calculados a partir das execuções registradas."
        actions={
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Período">
            <option value={7}>Últimos 7 dias</option>
            <option value={30}>Últimos 30 dias</option>
            <option value={90}>Últimos 90 dias</option>
          </select>
        } />
      <ErrorAlert error={error} />
      {loading && !data && <Spinner />}
      {data && (
        <>
          <div className="grid cols-4" style={{ marginBottom: 16 }}>
            <Stat label="Empresas atendidas ativas" value={fmtNumber(data.clients_active)} />
            <Stat label="Arquivos recebidos" value={fmtNumber(data.files_uploaded)} hint={`no período de ${data.period_days} dias`} />
            <Stat label="Execuções concluídas" value={fmtNumber(data.jobs_succeeded)} />
            <Stat label="Execuções com falha" value={fmtNumber(data.jobs_failed)} hint={data.jobs_pending ? `${data.jobs_pending} em andamento` : undefined} />
            <Stat label="Registros analisados" value={fmtNumber(data.records_processed)} />
            <Stat label="Erros encontrados" value={fmtNumber(data.errors_found)} />
            <Stat label="Alertas encontrados" value={fmtNumber(data.warnings_found)} />
            <Stat label="Comparações" value={fmtNumber(data.comparisons)} />
          </div>
          <div className="card flush">
            <div className="card-header" style={{ padding: "14px 16px 0" }}>
              <h2>Atividades recentes</h2>
            </div>
            {data.recent_activity.length === 0 ? (
              <div className="empty">
                Nenhuma atividade ainda. Comece <Link href="/empresas">cadastrando uma empresa atendida</Link> e enviando um arquivo.
              </div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Quando</th><th>Ação</th><th>Usuário</th></tr></thead>
                  <tbody>
                    {data.recent_activity.map((a) => (
                      <tr key={a.id}>
                        <td className="nowrap">{fmtDateTime(a.created_at)}</td>
                        <td>{AUDIT_ACTION[a.action] ?? a.action}</td>
                        <td>{a.actor_name ?? "Sistema"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
