"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, ConfirmButton, ErrorAlert, PageHeader, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { INFERRED_TYPE, fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { Profile, ProfileVersion } from "@/lib/types";

const STATUS: Record<string, string> = { approved: "Aprovada (atual)", superseded: "Substituída", draft: "Rascunho" };

export default function ProfileDetailPage({ params }: { params: { id: string } }) {
  const { can } = useSession();
  const profile = useAsync(() => api<Profile>(`/profiles/${params.id}`), [params.id]);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  if (profile.error) return <ErrorAlert error={profile.error} />;
  if (!profile.data) return <Spinner />;
  const p = profile.data;

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      profile.reload();
    } catch (e) {
      setError(e);
    }
  };

  const versionCard = (v: ProfileVersion) => (
    <div className="card" key={v.id}>
      <div className="card-header">
        <div>
          <h3>Versão {v.version} <Badge kind={v.approval_status}>{STATUS[v.approval_status]}</Badge></h3>
          <div className="small muted">
            Criada em {fmtDateTime(v.created_at)} · {v.source_format.toUpperCase()}
            {v.sheet_name && ` · aba "${v.sheet_name}"`} · cabeçalho na linha {v.header_row}
            {v.delimiter && ` · delimitador "${v.delimiter === "\t" ? "TAB" : v.delimiter}"`}
            {v.suggestion_source && ` · sugestões: ${v.suggestion_source}`}
          </div>
          {v.change_note && <div className="small">Motivo: {v.change_note}</div>}
          {v.source_file_id && <div className="small"><Link href={`/arquivos/${v.source_file_id}`}>Arquivo de referência</Link></div>}
        </div>
        <div className="row">
          {v.approval_status === "draft" && can("analyst") && (
            <button className="btn primary small" onClick={() => act(() => api(`/profiles/${p.id}/versions/${v.id}/approve`, { method: "POST" }))}>Aprovar</button>
          )}
          <button className="btn small" onClick={() => setOpen(open === v.id ? null : v.id)}>{open === v.id ? "Ocultar mapeamento" : "Ver mapeamento"}</button>
        </div>
      </div>
      {open === v.id && (
        <div className="table-wrap"><table>
          <thead><tr><th>Coluna de origem</th><th>Tipo</th><th>Campo de destino</th><th>Obrigatório</th><th>Transformações</th></tr></thead>
          <tbody>{v.mapping.map((m) => (
            <tr key={m.source_column}>
              <td>{m.source_column}</td>
              <td className="small">{INFERRED_TYPE[v.columns.find((c) => c.name === m.source_column)?.inferred_type ?? ""] ?? "—"}</td>
              <td>{m.status === "ignored" || !m.target_field ? <span className="muted">ignorada</span> : <code>{m.target_field}</code>}</td>
              <td>{m.required ? "sim" : "—"}</td>
              <td className="small">{m.transforms.join(", ") || "—"}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );

  return (
    <>
      <PageHeader title={p.name} subtitle={<>{p.client_name ?? "Toda a organização"} · <Badge kind={p.status === "active" ? "active" : ""}>{p.status === "active" ? "Ativo" : "Arquivado"}</Badge></>}
        actions={can("analyst") && (
          <ConfirmButton className="btn" label={p.status === "active" ? "Arquivar" : "Reativar"}
            confirmText={p.status === "active" ? "Perfis arquivados não são sugeridos para novos arquivos. O histórico é mantido." : "Reativar este perfil?"}
            onConfirm={() => act(() => api(`/profiles/${p.id}`, { method: "PATCH", body: { status: p.status === "active" ? "archived" : "active" } }))} />
        )} />
      <ErrorAlert error={error} />
      {p.description && <p>{p.description}</p>}
      <p className="muted small">Para criar uma nova versão, abra um arquivo com o novo layout e escolha “Nova versão de perfil existente” no mapeamento.</p>
      {(p.versions ?? []).map(versionCard)}
    </>
  );
}
