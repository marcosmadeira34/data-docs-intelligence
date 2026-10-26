"use client";

import { useState } from "react";
import { Alert, ErrorAlert, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { INFERRED_TYPE, fmtNumber, fmtPct } from "@/lib/format";
import { FileAsset, Inspection } from "@/lib/types";

const DELIMS: Record<string, string> = { ";": "Ponto e vírgula (;)", ",": "Vírgula (,)", "\t": "Tabulação", "|": "Barra vertical (|)" };

export function StructurePanel({ file, canEdit, onConfirmed }: { file: FileAsset; canEdit: boolean; onConfirmed: (f: FileAsset) => void }) {
  const base = file.inspection!;
  const [report, setReport] = useState<Inspection>(base);
  const [opts, setOpts] = useState({ ...base.options });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  const query = () => ({
    sheet: opts.sheet ?? undefined, header_row: opts.header_row || undefined,
    delimiter: file.detected_format === "csv" ? opts.delimiter ?? undefined : undefined,
    encoding: file.detected_format === "csv" ? opts.encoding ?? undefined : undefined,
  });

  const preview = async (next = opts) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const r = await api<Inspection>(`/files/${file.id}/profile`, { query: {
        sheet: next.sheet ?? undefined, header_row: next.header_row || undefined,
        delimiter: file.detected_format === "csv" ? next.delimiter ?? undefined : undefined,
        encoding: file.detected_format === "csv" ? next.encoding ?? undefined : undefined,
      } });
      setReport(r);
      setOpts({ ...r.options });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const f = await api<FileAsset>(`/files/${file.id}/structure`, { method: "POST", body: query() });
      setReport(f.inspection!);
      setSaved(true);
      onConfirmed(f);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const change = (patch: Partial<typeof opts>) => {
    const next = { ...opts, ...patch };
    if (patch.sheet !== undefined) next.header_row = 0;
    setOpts(next);
    preview(next);
  };

  return (
    <div className="stack">
      <ErrorAlert error={error} />
      {report.ambiguities.length > 0 && (
        <Alert kind="warning" title="Confirme a interpretação do arquivo">
          <ul>{report.ambiguities.map((a, i) => <li key={i}>{a.message}</li>)}</ul>
        </Alert>
      )}
      {report.warnings.length > 0 && (
        <Alert kind="info" title="Observações da inspeção">
          <ul>{report.warnings.map((w, i) => <li key={i}>{w.message}</li>)}</ul>
        </Alert>
      )}
      {saved && <Alert kind="success">Estrutura confirmada e salva.</Alert>}

      <div className="card">
        <div className="card-header"><h2>Leitura do arquivo</h2>{busy && <Spinner label="Reinspecionando…" />}</div>
        <div className="form-grid">
          {file.detected_format === "xlsx" && (
            <label className="field">Aba
              <select value={opts.sheet ?? ""} onChange={(e) => change({ sheet: e.target.value })} disabled={busy}>
                {report.sheets.map((s) => <option key={s.name} value={s.name}>{s.name}{s.visible ? "" : " (oculta)"}{s.dimension ? ` — ${s.dimension}` : ""}</option>)}
              </select>
            </label>
          )}
          <label className="field">Linha do cabeçalho
            <select value={opts.header_row} onChange={(e) => change({ header_row: Number(e.target.value) })} disabled={busy}>
              {Array.from(new Set([opts.header_row, ...report.header_candidates.map((c) => c.row), 1, 2, 3, 4, 5]))
                .filter((n) => n > 0).sort((a, b) => a - b).map((n) => {
                  const cand = report.header_candidates.find((c) => c.row === n);
                  return <option key={n} value={n}>Linha {n}{cand ? ` — ${cand.values.slice(0, 3).join(", ")}` : ""}</option>;
                })}
            </select>
          </label>
          {file.detected_format === "csv" && (
            <>
              <label className="field">Delimitador
                <select value={opts.delimiter ?? ";"} onChange={(e) => change({ delimiter: e.target.value })} disabled={busy}>
                  {Object.entries(DELIMS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label className="field">Codificação
                <select value={opts.encoding ?? "utf-8"} onChange={(e) => change({ encoding: e.target.value })} disabled={busy}>
                  {["utf-8", "utf-8-sig", "cp1252", "latin-1", "utf-16"].map((e) => <option key={e} value={e}>{e}</option>)}
                </select>
              </label>
            </>
          )}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <span className="muted">{fmtNumber(report.row_count)} registros · {report.columns.length} colunas
            {report.malformed_rows.count > 0 && ` · ${report.malformed_rows.count} linha(s) malformada(s)`}</span>
          <span style={{ flex: 1 }} />
          {canEdit && <button className="btn primary" onClick={confirm} disabled={busy}>
            {file.structure_confirmed ? "Confirmar novamente" : "Confirmar estrutura"}</button>}
        </div>
      </div>

      <div className="card flush">
        <div className="card-header" style={{ padding: "14px 16px 0" }}><h2>Colunas identificadas</h2></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Coluna</th><th>Tipo inferido</th><th className="right">Vazios</th><th>Formato</th><th>Exemplos (mascarados)</th></tr></thead>
            <tbody>
              {report.columns.map((c) => (
                <tr key={c.index}>
                  <td className="muted">{c.index + 1}</td>
                  <td><strong>{c.name}</strong></td>
                  <td>{INFERRED_TYPE[c.inferred_type] ?? c.inferred_type}</td>
                  <td className="num">{fmtPct(c.null_ratio)}</td>
                  <td className="small">{c.number_style ? `número ${c.number_style === "br" ? "brasileiro" : "americano"}` : c.date_format ?? "—"}</td>
                  <td className="small muted">{c.samples.join(" · ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card flush">
        <div className="card-header" style={{ padding: "14px 16px 0" }}><h2>Prévia ({report.preview.length} primeiras linhas)</h2></div>
        <div className="table-wrap preview">
          <table>
            <thead><tr>{report.columns.map((c) => <th key={c.index}>{c.name}</th>)}</tr></thead>
            <tbody>{report.preview.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} title={v}>{v}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
