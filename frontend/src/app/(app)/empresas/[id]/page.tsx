"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, ConfirmButton, Empty, ErrorAlert, PageHeader, Spinner, Stat, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { ERROR_KIND, JOB_STATUS, fmtBytes, fmtDateTime, fmtNumber } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Client, ClientForm } from "@/components/ClientForm";

export default function ClientDetailPage({ params }: { params: { id: string } }) {
  const { can } = useSession();
  const [editing, setEditing] = useState(false);
  const client = useAsync(() => api<Client & { file_count: number; job_count: number; last_activity_at: string | null }>(`/clients/${params.id}`), [params.id]);
  const files = useAsync(() => api<{ items: any[] }>("/files", { query: { client_id: params.id, limit: 20 } }), [params.id]);
  const jobs = useAsync(() => api<{ items: any[] }>("/jobs", { query: { client_id: params.id, limit: 20 } }), [params.id]);

  if (client.error) return <ErrorAlert error={client.error} />;
  if (!client.data) return <Spinner />;
  const c = client.data;
  const toggle = async () => {
    await api(`/clients/${c.id}`, { method: "PATCH", body: { status: c.status === "active" ? "inactive" : "active" } });
    client.reload();
  };

  return (
    <>
      <PageHeader title={c.name} subtitle={<>Empresa atendida · <Badge kind={c.status === "active" ? "active" : ""}>{c.status === "active" ? "Ativa" : "Desativada"}</Badge></>}
        actions={can("analyst") && (
          <>
            <Link className="btn primary" href={`/arquivos?client=${c.id}`}>Enviar arquivo</Link>
            <button className="btn" onClick={() => setEditing(true)}>Editar</button>
            <ConfirmButton label={c.status === "active" ? "Desativar" : "Reativar"} className="btn"
              confirmText={c.status === "active" ? "Empresas desativadas não podem receber novos arquivos. O histórico é preservado." : "Reativar esta empresa?"}
              onConfirm={toggle} />
          </>
        )} />
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat label="Arquivos" value={fmtNumber(c.file_count)} />
        <Stat label="Execuções" value={fmtNumber(c.job_count)} />
        <Stat label="Última atividade" value={<span style={{ fontSize: 15 }}>{fmtDateTime(c.last_activity_at)}</span>} />
      </div>
      <div className="grid cols-2">
        <div className="card flush">
          <div className="card-header" style={{ padding: "14px 16px 0" }}><h2>Arquivos recentes</h2></div>
          {files.data?.items.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Arquivo</th><th>Tamanho</th><th>Enviado</th></tr></thead>
              <tbody>{files.data.items.map((f) => (
                <tr key={f.id}><td><Link href={`/arquivos/${f.id}`}>{f.original_filename}</Link></td><td className="nowrap">{fmtBytes(f.size_bytes)}</td><td className="nowrap">{fmtDateTime(f.created_at)}</td></tr>
              ))}</tbody>
            </table></div>
          ) : <Empty>Nenhum arquivo enviado.</Empty>}
        </div>
        <div className="card flush">
          <div className="card-header" style={{ padding: "14px 16px 0" }}><h2>Histórico de execuções</h2></div>
          {jobs.data?.items.length ? (
            <div className="table-wrap"><table>
              <thead><tr><th>Arquivo</th><th>Situação</th><th className="right">Erros</th><th>Data</th></tr></thead>
              <tbody>{jobs.data.items.map((j) => (
                <tr key={j.id}>
                  <td><Link href={`/execucoes/${j.id}`}>{j.input_snapshot?.file_name ?? j.id}</Link></td>
                  <td><Badge kind={j.status}>{JOB_STATUS[j.status]}</Badge>{j.error_kind && <div className="small muted">{ERROR_KIND[j.error_kind]}</div>}</td>
                  <td className="num">{fmtNumber(j.error_count)}</td>
                  <td className="nowrap">{fmtDateTime(j.created_at)}</td>
                </tr>
              ))}</tbody>
            </table></div>
          ) : <Empty>Nenhuma execução.</Empty>}
        </div>
      </div>
      {c.notes && <div className="card"><h3>Observações</h3><p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{c.notes}</p></div>}
      {editing && <ClientForm initial={c} onSaved={client.reload} onClose={() => setEditing(false)} />}
    </>
  );
}
