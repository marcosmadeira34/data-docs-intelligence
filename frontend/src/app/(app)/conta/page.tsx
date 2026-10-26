"use client";

import { useState } from "react";
import { Alert, ErrorAlert, PageHeader, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { ROLES, fmtNumber } from "@/lib/format";
import { useSession } from "@/lib/session";

const METRICS: Record<string, string> = { files: "Arquivos enviados", records: "Registros processados", jobs: "Execuções", comparisons: "Comparações" };

export default function AccountPage() {
  const { me } = useSession();
  const usage = useAsync(() => api("/organizations/current/usage"), []);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [error, setError] = useState<unknown>(null);
  const [ok, setOk] = useState(false);

  const change = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setOk(false);
    try {
      await api("/me/password", { method: "POST", body: pw });
      setOk(true);
      setPw({ current_password: "", new_password: "" });
    } catch (err) {
      setError(err);
    }
  };

  return (
    <>
      <PageHeader title="Minha conta e plano" subtitle={me ? `${me.user.name} · ${me.user.email} · ${ROLES[me.role]} em ${me.organization.name}` : undefined} />
      <div className="grid cols-2">
        <div className="card">
          <h2>Plano e consumo do mês</h2>
          <ErrorAlert error={usage.error} />
          {!usage.data ? <Spinner /> : (
            <>
              <p className="muted">Plano <strong>{usage.data.plan_name}</strong> · situação {usage.data.subscription_status} · período {usage.data.period}</p>
              <table>
                <thead><tr><th>Métrica</th><th className="right">Utilizado</th><th className="right">Limite</th></tr></thead>
                <tbody>{Object.entries(METRICS).map(([k, label]) => (
                  <tr key={k}><td>{label}</td><td className="num">{fmtNumber(usage.data.usage[k])}</td>
                    <td className="num">{usage.data.limits[k] == null ? "ilimitado" : fmtNumber(usage.data.limits[k])}</td></tr>
                ))}</tbody>
              </table>
              <p className="muted small">Limites aplicados pelo servidor. Cobrança automática ainda não está habilitada.</p>
            </>
          )}
        </div>
        <form className="card stack" onSubmit={change}>
          <h2>Alterar senha</h2>
          <ErrorAlert error={error} />
          {ok && <Alert kind="success">Senha alterada.</Alert>}
          <label className="field">Senha atual<input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></label>
          <label className="field">Nova senha<input type="password" autoComplete="new-password" minLength={10} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></label>
          <button className="btn primary" type="submit">Alterar senha</button>
        </form>
      </div>
    </>
  );
}
