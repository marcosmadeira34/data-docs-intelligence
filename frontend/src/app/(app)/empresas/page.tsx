"use client";

import Link from "next/link";
import { useState } from "react";
import { Client, ClientForm } from "@/components/ClientForm";
import { Badge, Empty, ErrorAlert, PageHeader, Pagination, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function ClientsPage() {
  const { can } = useSession();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("active");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const { data, error, loading, reload } = useAsync(
    () => api<{ items: Client[]; total: number }>("/clients", { query: { q, status, limit: 50, offset } }), [q, status, offset]);

  return (
    <>
      <PageHeader title="Empresas atendidas" subtitle="Clientes do escritório/BPO cujos arquivos são processados."
        actions={can("analyst") && <button className="btn primary" onClick={() => setCreating(true)}>Nova empresa</button>} />
      <div className="card row">
        <input placeholder="Buscar por nome, código ou CNPJ" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} style={{ flex: 1, minWidth: 220 }} />
        <select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} aria-label="Situação">
          <option value="active">Ativas</option>
          <option value="inactive">Desativadas</option>
          <option value="">Todas</option>
        </select>
      </div>
      <ErrorAlert error={error} />
      <div className="card flush">
        {loading && !data ? <div className="empty"><Spinner /></div> : data && data.items.length === 0 ? (
          <Empty>Nenhuma empresa encontrada.{can("analyst") && " Cadastre a primeira para começar a enviar arquivos."}</Empty>
        ) : data && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Empresa</th><th>Código</th><th>CNPJ</th><th>Situação</th><th>Cadastro</th></tr></thead>
              <tbody>
                {data.items.map((c) => (
                  <tr key={c.id}>
                    <td><Link href={`/empresas/${c.id}`}>{c.name}</Link></td>
                    <td>{c.external_reference ?? "—"}</td>
                    <td>{c.tax_id ?? "—"}</td>
                    <td><Badge kind={c.status === "active" ? "active" : ""}>{c.status === "active" ? "Ativa" : "Desativada"}</Badge></td>
                    <td className="nowrap">{fmtDateTime(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination total={data.total} limit={50} offset={offset} onChange={setOffset} />
          </div>
        )}
      </div>
      {creating && <ClientForm onSaved={reload} onClose={() => setCreating(false)} />}
    </>
  );
}
