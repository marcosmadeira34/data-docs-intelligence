"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Empty, ErrorAlert, PageHeader, Pagination, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { JOB_STATUS, fmtDateTime, fmtNumber } from "@/lib/format";
import { useSession } from "@/lib/session";

export default function ComparisonsPage() {
  const { can } = useSession();
  const [offset, setOffset] = useState(0);
  const list = useAsync(() => api<{ items: any[]; total: number }>("/comparisons", { query: { limit: 50, offset } }), [offset]);

  return (
    <>
      <PageHeader title="Comparações" subtitle="Confronto entre dois arquivos por chave de correspondência explícita."
        actions={can("analyst") && <Link className="btn primary" href="/comparacoes/nova">Nova comparação</Link>} />
      <ErrorAlert error={list.error} />
      <div className="card flush">
        {list.loading && !list.data ? <div className="empty"><Spinner /></div> : list.data && list.data.items.length === 0 ? (
          <Empty>Nenhuma comparação realizada.</Empty>
        ) : list.data && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Comparação</th><th>Arquivo A</th><th>Arquivo B</th><th>Situação</th><th className="right">Divergências</th>
                <th className="right">Só em A</th><th className="right">Só em B</th><th>Data</th></tr></thead>
              <tbody>
                {list.data.items.map((c) => (
                  <tr key={c.id}>
                    <td><Link href={`/comparacoes/${c.id}`}>{c.name || c.id.slice(0, 8)}</Link></td>
                    <td className="small">{c.input_snapshot?.a?.file_name}</td>
                    <td className="small">{c.input_snapshot?.b?.file_name}</td>
                    <td><Badge kind={c.status}>{JOB_STATUS[c.status]}</Badge></td>
                    <td className="num">{fmtNumber(c.summary?.mismatch)}</td>
                    <td className="num">{fmtNumber(c.summary?.only_a)}</td>
                    <td className="num">{fmtNumber(c.summary?.only_b)}</td>
                    <td className="nowrap">{fmtDateTime(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination total={list.data.total} limit={50} offset={offset} onChange={setOffset} />
          </div>
        )}
      </div>
    </>
  );
}
