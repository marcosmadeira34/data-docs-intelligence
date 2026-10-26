"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, ErrorAlert, PageHeader, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { FileAsset } from "@/lib/types";

type Pair = { column_a: string; column_b: string; kind?: string; abs_tolerance?: string; pct_tolerance?: string; number_style_a?: string; number_style_b?: string; warning?: string };
type Suggestion = { key_pairs: Pair[]; compare_pairs: Pair[]; loose_pairs: Pair[]; columns_a: string[]; columns_b: string[]; warnings: string[] };

const KEY_NORM: Record<string, string> = { trim: "remover espaços", case_insensitive: "ignorar maiúsculas", strip_accents: "ignorar acentos",
  digits_only: "somente dígitos", strip_leading_zeros: "ignorar zeros à esquerda" };

export default function NewComparisonPage() {
  const router = useRouter();
  const files = useAsync(() => api<{ items: FileAsset[] }>("/files", { query: { limit: 200 } }), []);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [name, setName] = useState("");
  const [sug, setSug] = useState<Suggestion | null>(null);
  const [keys, setKeys] = useState<Pair[]>([]);
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [keyNorm, setKeyNorm] = useState<string[]>(["trim", "case_insensitive"]);
  const [nullMode, setNullMode] = useState("divergent");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const suggest = async () => {
    setError(null);
    try {
      const s = await api<Suggestion>("/comparisons/suggest", { method: "POST", body: { file_a_id: a, file_b_id: b } });
      setSug(s);
      setKeys(s.key_pairs.length ? s.key_pairs : [{ column_a: s.columns_a[0], column_b: s.columns_b[0] }]);
      setPairs([...s.compare_pairs, ...s.loose_pairs].map(({ warning, ...p }) => p));
    } catch (e) {
      setError(e);
    }
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const c = await api("/comparisons", { method: "POST", body: {
        name: name || null, file_a_id: a, file_b_id: b,
        config: { key_pairs: keys, compare_pairs: pairs.map((p) => ({ ...p, abs_tolerance: p.abs_tolerance || "0", pct_tolerance: p.pct_tolerance || "0" })),
          key_normalization: keyNorm, null_vs_value: nullMode } } });
      router.push(`/comparacoes/${c.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const fileOptions = (files.data?.items ?? []).map((f) => <option key={f.id} value={f.id}>{f.original_filename} — {new Date(f.created_at).toLocaleDateString("pt-BR")}</option>);
  const updPair = (i: number, patch: Partial<Pair>) => setPairs(pairs.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  return (
    <>
      <PageHeader title="Nova comparação" subtitle="Registros só são pareados quando a chave configurada coincide; nada é pareado por semelhança." />
      <ErrorAlert error={error ?? files.error} />
      <div className="card">
        <div className="form-grid">
          <label className="field">Arquivo A (referência)
            <select value={a} onChange={(e) => { setA(e.target.value); setSug(null); }}><option value="">Selecione…</option>{fileOptions}</select>
          </label>
          <label className="field">Arquivo B (comparado)
            <select value={b} onChange={(e) => { setB(e.target.value); setSug(null); }}><option value="">Selecione…</option>{fileOptions}</select>
          </label>
          <label className="field">Nome (opcional)
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ex.: ERP x extrato — setembro" />
          </label>
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={suggest} disabled={!a || !b || a === b}>Configurar colunas</button>
        </div>
      </div>

      {sug && (
        <>
          {sug.warnings.map((w, i) => <Alert key={i} kind="warning">{w}</Alert>)}
          {sug.loose_pairs.map((p, i) => p.warning && <Alert key={`l${i}`} kind="info">{p.warning}</Alert>)}
          <div className="card">
            <h2>Chave de correspondência</h2>
            {keys.map((k, i) => (
              <div key={i} className="row" style={{ marginBottom: 8 }}>
                <select value={k.column_a} onChange={(e) => setKeys(keys.map((x, j) => (j === i ? { ...x, column_a: e.target.value } : x)))}>
                  {sug.columns_a.map((c) => <option key={c}>{c}</option>)}</select>
                <span>=</span>
                <select value={k.column_b} onChange={(e) => setKeys(keys.map((x, j) => (j === i ? { ...x, column_b: e.target.value } : x)))}>
                  {sug.columns_b.map((c) => <option key={c}>{c}</option>)}</select>
                {keys.length > 1 && <button className="btn small" onClick={() => setKeys(keys.filter((_, j) => j !== i))}>Remover</button>}
              </div>
            ))}
            {keys.length < 4 && <button className="btn small" onClick={() => setKeys([...keys, { column_a: sug.columns_a[0], column_b: sug.columns_b[0] }])}>Adicionar coluna à chave</button>}
            <div className="row" style={{ marginTop: 12 }}>
              <span className="muted small">Normalização da chave:</span>
              {Object.entries(KEY_NORM).map(([k, v]) => (
                <label key={k} className="checkbox"><input type="checkbox" checked={keyNorm.includes(k)}
                  onChange={(e) => setKeyNorm(e.target.checked ? [...keyNorm, k] : keyNorm.filter((x) => x !== k))} /> {v}</label>
              ))}
            </div>
          </div>
          <div className="card flush">
            <div className="card-header" style={{ padding: "14px 16px 0" }}>
              <h2>Campos comparados</h2>
              <button className="btn small" onClick={() => setPairs([...pairs, { column_a: sug.columns_a[0], column_b: sug.columns_b[0], kind: "text" }])}>Adicionar campo</button>
            </div>
            <div className="table-wrap"><table>
              <thead><tr><th>Coluna em A</th><th>Coluna em B</th><th>Tipo</th><th>Tolerância absoluta</th><th>Tolerância %</th><th></th></tr></thead>
              <tbody>{pairs.map((p, i) => (
                <tr key={i}>
                  <td><select value={p.column_a} onChange={(e) => updPair(i, { column_a: e.target.value })}>{sug.columns_a.map((c) => <option key={c}>{c}</option>)}</select></td>
                  <td><select value={p.column_b} onChange={(e) => updPair(i, { column_b: e.target.value })}>{sug.columns_b.map((c) => <option key={c}>{c}</option>)}</select></td>
                  <td><select value={p.kind ?? "text"} onChange={(e) => updPair(i, { kind: e.target.value })}>
                    <option value="text">Texto</option><option value="number">Número</option><option value="date">Data</option></select></td>
                  <td>{p.kind === "number" ? <input style={{ width: 90 }} value={p.abs_tolerance ?? "0"} onChange={(e) => updPair(i, { abs_tolerance: e.target.value })} /> : "—"}</td>
                  <td>{p.kind === "number" ? <input style={{ width: 90 }} value={p.pct_tolerance ?? "0"} onChange={(e) => updPair(i, { pct_tolerance: e.target.value })}
                    title="Fração: 0.01 = 1%" /> : "—"}</td>
                  <td><button className="btn small" onClick={() => setPairs(pairs.filter((_, j) => j !== i))}>Remover</button></td>
                </tr>
              ))}</tbody>
            </table></div>
            <div className="row" style={{ padding: 12 }}>
              <label className="field">Valor ausente em um dos lados
                <select value={nullMode} onChange={(e) => setNullMode(e.target.value)}>
                  <option value="divergent">Considerar divergência</option>
                  <option value="ignore">Ignorar</option>
                </select>
              </label>
            </div>
          </div>
          <button className="btn primary" onClick={submit} disabled={busy || keys.length === 0}>{busy ? "Comparando…" : "Comparar"}</button>
        </>
      )}
    </>
  );
}
