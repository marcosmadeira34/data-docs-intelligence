"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Empty, ErrorAlert, PageHeader, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { Profile } from "@/lib/types";

export default function ProfilesPage() {
  const [status, setStatus] = useState("active");
  const list = useAsync(() => api<{ items: Profile[]; total: number }>("/profiles", { query: { status, limit: 200 } }), [status]);

  return (
    <>
      <PageHeader title="Perfis de layout" subtitle="Estruturas e mapeamentos aprovados, reutilizados quando um novo arquivo tem layout compatível." />
      <div className="card row">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Situação">
          <option value="active">Ativos</option><option value="archived">Arquivados</option><option value="">Todos</option>
        </select>
      </div>
      <ErrorAlert error={list.error} />
      <div className="card flush">
        {list.loading && !list.data ? <div className="empty"><Spinner /></div> : list.data && list.data.items.length === 0 ? (
          <Empty>Nenhum perfil. Perfis são criados ao aprovar o mapeamento de um arquivo.</Empty>
        ) : list.data && (
          <div className="table-wrap"><table>
            <thead><tr><th>Perfil</th><th>Abrangência</th><th>Versão atual</th><th>Formato</th><th>Colunas</th><th>Aprovado em</th><th>Situação</th></tr></thead>
            <tbody>{list.data.items.map((p) => (
              <tr key={p.id}>
                <td><Link href={`/perfis/${p.id}`}>{p.name}</Link>{p.description && <div className="small muted">{p.description}</div>}</td>
                <td>{p.client_name ?? "Toda a organização"}</td>
                <td>{p.current_version ? <>v{p.current_version.version} <Badge kind="approved">aprovada</Badge></> : <Badge kind="draft">sem versão aprovada</Badge>}
                  <div className="small muted">{p.version_count} versão(ões)</div></td>
                <td>{p.current_version?.source_format.toUpperCase() ?? "—"}</td>
                <td className="num">{p.current_version?.columns.length ?? "—"}</td>
                <td className="nowrap">{fmtDateTime(p.current_version?.approved_at)}</td>
                <td><Badge kind={p.status === "active" ? "active" : ""}>{p.status === "active" ? "Ativo" : "Arquivado"}</Badge></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
    </>
  );
}
