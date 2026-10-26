"use client";

import { useState } from "react";
import { Alert, Empty, ErrorAlert, PageHeader, Pagination, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { AUDIT_ACTION, fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function AuditPage() {
  const { can } = useSession();
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const events = useAsync(() => (can("admin") ? api<{ items: any[]; total: number }>("/audit-events", { query: { action, limit: 50, offset } }) : Promise.resolve(null)),
    [action, offset]);
  if (!can("admin")) return <Alert kind="warning">Somente administradores podem consultar a auditoria.</Alert>;

  return (
    <>
      <PageHeader title="Auditoria" subtitle="Registro de operações relevantes. Não contém conteúdo de arquivos." />
      <div className="card row">
        <select value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} aria-label="Ação">
          <option value="">Todas as ações</option>
          {Object.entries(AUDIT_ACTION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <ErrorAlert error={events.error} />
      <div className="card flush">
        {!events.data ? <div className="empty"><Spinner /></div> : events.data.items.length === 0 ? <Empty>Nenhum evento.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Quando</th><th>Ação</th><th>Usuário</th><th>Entidade</th><th>Detalhes</th></tr></thead>
            <tbody>{events.data.items.map((e) => (
              <tr key={e.id}>
                <td className="nowrap">{fmtDateTime(e.created_at)}</td>
                <td>{AUDIT_ACTION[e.action] ?? e.action}</td>
                <td>{e.actor_name ?? "Sistema"}</td>
                <td className="small">{e.entity_type}<div className="mono muted">{e.entity_id}</div></td>
                <td className="small mono">{Object.keys(e.details ?? {}).length ? JSON.stringify(e.details) : "—"}</td>
              </tr>
            ))}</tbody>
          </table>
          <Pagination total={events.data.total} limit={50} offset={offset} onChange={setOffset} /></div>
        )}
      </div>
    </>
  );
}
