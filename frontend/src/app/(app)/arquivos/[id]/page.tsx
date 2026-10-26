"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { MappingPanel } from "@/components/files/MappingPanel";
import { RunPanel } from "@/components/files/RunPanel";
import { StructurePanel } from "@/components/files/StructurePanel";
import { Alert, Badge, ConfirmButton, ErrorAlert, PageHeader, Spinner, useAsync } from "@/components/ui";
import { api, downloadUrl } from "@/lib/api";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { FileAsset } from "@/lib/types";

type Tab = "structure" | "mapping" | "run";

export default function FileDetailPage({ params }: { params: { id: string } }) {
  const { can } = useSession();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("structure");
  const [profileId, setProfileId] = useState("");
  const { data: file, error, setData } = useAsync(() => api<FileAsset>(`/files/${params.id}`), [params.id]);
  const client = useAsync(() => (file ? api(`/clients/${file.client_account_id}`) : Promise.resolve(null)), [file?.client_account_id]);

  if (error) return <ErrorAlert error={error} />;
  if (!file) return <Spinner />;
  const deleted = file.status === "deleted";

  return (
    <>
      <PageHeader title={file.original_filename}
        subtitle={<>
          {client.data && <Link href={`/empresas/${file.client_account_id}`}>{client.data.name}</Link>} · {file.detected_format.toUpperCase()} ·{" "}
          {fmtBytes(file.size_bytes)} · enviado em {fmtDateTime(file.created_at)} ·{" "}
          {file.structure_confirmed ? <Badge kind="success">Estrutura confirmada</Badge> : <Badge kind="warning">Estrutura detectada</Badge>}
        </>}
        actions={!deleted && (
          <>
            <a className="btn" href={downloadUrl(`/files/${file.id}/download`)}>Baixar original</a>
            {can("admin") && <ConfirmButton label="Excluir conteúdo" confirmText="O conteúdo do arquivo e a prévia serão removidos. Metadados, hash e histórico de execuções são mantidos para auditoria."
              onConfirm={async () => { await api(`/files/${file.id}`, { method: "DELETE" }); router.push("/arquivos"); }} />}
          </>
        )} />
      <dl className="kv card">
        <dt>SHA-256</dt><dd className="mono">{file.content_hash}</dd>
        <dt>Retenção até</dt><dd>{fmtDateTime(file.retention_until)}</dd>
        {file.duplicate_of_id && <><dt>Duplicidade</dt><dd>Conteúdo idêntico a <Link href={`/arquivos/${file.duplicate_of_id}`}>outro arquivo</Link> desta empresa.</dd></>}
      </dl>
      {deleted ? (
        <Alert kind="warning" title="Conteúdo excluído">O conteúdo foi removido em {fmtDateTime(file.deleted_at)}. O histórico de execuções permanece disponível.</Alert>
      ) : (
        <>
          <div className="tabs" role="tablist">
            <button className={tab === "structure" ? "active" : ""} onClick={() => setTab("structure")}>1. Estrutura</button>
            <button className={tab === "mapping" ? "active" : ""} onClick={() => setTab("mapping")}>2. Mapeamento e perfil</button>
            <button className={tab === "run" ? "active" : ""} onClick={() => setTab("run")}>3. Executar validação</button>
          </div>
          {tab === "structure" && <StructurePanel file={file} canEdit={can("analyst")} onConfirmed={(f) => setData(f)} />}
          {tab === "mapping" && <MappingPanel key={JSON.stringify(file.read_options)} file={file} canEdit={can("analyst")}
            onUseProfile={(id) => { setProfileId(id); setTab("run"); }} />}
          {tab === "run" && <RunPanel file={file} profileId={profileId} canRun={can("analyst")} />}
        </>
      )}
    </>
  );
}
