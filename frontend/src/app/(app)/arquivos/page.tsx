"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";
import { Badge, Empty, ErrorAlert, PageHeader, Pagination, Spinner, useAsync } from "@/components/ui";
import { api, uploadFile } from "@/lib/api";
import { fmtBytes, fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { FileAsset } from "@/lib/types";

function FilesInner() {
  const { can } = useSession();
  const router = useRouter();
  const params = useSearchParams();
  const [clientId, setClientId] = useState(params.get("client") ?? "");
  const [filterClient, setFilterClient] = useState(params.get("client") ?? "");
  const [offset, setOffset] = useState(0);
  const [progress, setProgress] = useState<number | null>(null);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const clients = useAsync(() => api<{ items: { id: string; name: string }[] }>("/clients", { query: { status: "active", limit: 200 } }), []);
  const files = useAsync(() => api<{ items: FileAsset[]; total: number }>("/files", { query: { client_id: filterClient, limit: 50, offset } }),
    [filterClient, offset]);
  const clientName = (id: string) => clients.data?.items.find((c) => c.id === id)?.name ?? "—";

  const upload = async () => {
    const f = fileInput.current?.files?.[0];
    if (!f || !clientId) return;
    setUploadError(null);
    setProgress(0);
    try {
      const created = await uploadFile(clientId, f, setProgress);
      router.push(`/arquivos/${created.id}`);
    } catch (e) {
      setUploadError(e);
      setProgress(null);
    }
  };

  return (
    <>
      <PageHeader title="Arquivos" subtitle="Envie planilhas CSV ou XLSX. A estrutura é identificada automaticamente e você confirma o que for ambíguo." />
      {can("analyst") && (
        <div className="card">
          <h2>Enviar arquivo</h2>
          <ErrorAlert error={uploadError} />
          <div className="form-grid" style={{ alignItems: "end" }}>
            <label className="field">Empresa atendida
              <select value={clientId} onChange={(e) => setClientId(e.target.value)}>
                <option value="">Selecione…</option>
                {clients.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
            <label className="field">Arquivo (.csv, .txt, .tsv, .xlsx)
              <input ref={fileInput} type="file" accept=".csv,.txt,.tsv,.xlsx" />
            </label>
            <button className="btn primary" onClick={upload} disabled={!clientId || progress !== null}>Enviar e inspecionar</button>
          </div>
          {clients.data && clients.data.items.length === 0 && (
            <p className="muted small">Nenhuma empresa ativa. <Link href="/empresas">Cadastre uma empresa</Link> antes de enviar arquivos.</p>
          )}
          {progress !== null && (
            <div className="stack" style={{ marginTop: 12 }}>
              <div className="progress"><div style={{ width: `${progress}%` }} /></div>
              <span className="muted small">{progress < 100 ? `Enviando… ${progress}%` : "Envio concluído. Validando formato e inspecionando estrutura…"}</span>
            </div>
          )}
        </div>
      )}
      <div className="card row">
        <label className="field" style={{ minWidth: 260 }}>Filtrar por empresa
          <select value={filterClient} onChange={(e) => { setFilterClient(e.target.value); setOffset(0); }}>
            <option value="">Todas</option>
            {clients.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      </div>
      <ErrorAlert error={files.error} />
      <div className="card flush">
        {files.loading && !files.data ? <div className="empty"><Spinner /></div> : files.data && files.data.items.length === 0 ? (
          <Empty>Nenhum arquivo enviado.</Empty>
        ) : files.data && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Arquivo</th><th>Empresa</th><th>Formato</th><th>Tamanho</th><th>Estrutura</th><th>Enviado</th></tr></thead>
              <tbody>
                {files.data.items.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link href={`/arquivos/${f.id}`}>{f.original_filename}</Link>
                      {f.duplicate_of_id && <div className="small muted">Conteúdo idêntico a um arquivo já enviado</div>}
                    </td>
                    <td>{clientName(f.client_account_id)}</td>
                    <td>{f.detected_format.toUpperCase()}</td>
                    <td className="nowrap">{fmtBytes(f.size_bytes)}</td>
                    <td>{f.structure_confirmed ? <Badge kind="success">Confirmada</Badge> : <Badge kind="warning">Detectada</Badge>}</td>
                    <td className="nowrap">{fmtDateTime(f.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination total={files.data.total} limit={50} offset={offset} onChange={setOffset} />
          </div>
        )}
      </div>
    </>
  );
}

export default function FilesPage() {
  return (
    <Suspense>
      <FilesInner />
    </Suspense>
  );
}
