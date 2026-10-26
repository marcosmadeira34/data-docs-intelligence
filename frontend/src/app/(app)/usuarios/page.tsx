"use client";

import { useState } from "react";
import { Alert, Badge, ErrorAlert, Modal, PageHeader, Spinner, useAsync } from "@/components/ui";
import { api } from "@/lib/api";
import { ROLES, fmtDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";

type Member = { id: string; user_id: string; name: string; email: string; role: string; status: string; created_at: string; last_login_at: string | null };

export default function UsersPage() {
  const { me, can } = useSession();
  const members = useAsync(() => api<Member[]>("/organizations/current/members"), []);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", role: "analyst" });
  const [error, setError] = useState<unknown>(null);
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null);

  if (!can("admin")) return <Alert kind="warning">Somente administradores podem gerenciar usuários.</Alert>;

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      members.reload();
    } catch (e) {
      setError(e);
    }
  };
  const add = () => act(async () => {
    const r = await api("/organizations/current/members", { method: "POST", body: form });
    setAdding(false);
    if (r.temporary_password) setSecret({ email: r.member.email, password: r.temporary_password });
    setForm({ name: "", email: "", role: "analyst" });
  });
  const reset = (m: Member) => act(async () => {
    const r = await api(`/organizations/current/members/${m.id}/reset-password`, { method: "POST" });
    setSecret({ email: m.email, password: r.temporary_password });
  });

  return (
    <>
      <PageHeader title="Usuários e permissões" subtitle="Papéis: Proprietário (tudo), Administrador (usuários e exclusões), Analista (operação), Leitura (consulta)."
        actions={<button className="btn primary" onClick={() => setAdding(true)}>Adicionar membro</button>} />
      <ErrorAlert error={error ?? members.error} />
      {secret && (
        <Alert kind="warning" title="Senha temporária (exibida apenas uma vez)">
          Usuário <strong>{secret.email}</strong>: <code>{secret.password}</code>. Entregue por canal seguro e peça a troca no primeiro acesso.
          <div><button className="btn small" style={{ marginTop: 6 }} onClick={() => setSecret(null)}>Ocultar</button></div>
        </Alert>
      )}
      <div className="card flush">
        {!members.data ? <div className="empty"><Spinner /></div> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Nome</th><th>E-mail</th><th>Papel</th><th>Situação</th><th>Último acesso</th><th></th></tr></thead>
            <tbody>{members.data.map((m) => {
              const self = m.user_id === me?.user.id;
              const locked = self || (m.role === "owner" && me?.role !== "owner");
              return (
                <tr key={m.id}>
                  <td>{m.name}{self && <span className="muted small"> (você)</span>}</td>
                  <td>{m.email}</td>
                  <td>
                    <select value={m.role} disabled={locked} onChange={(e) => act(() => api(`/organizations/current/members/${m.id}`, { method: "PATCH", body: { role: e.target.value } }))}>
                      {Object.entries(ROLES).filter(([k]) => k !== "owner" || me?.role === "owner" || m.role === "owner").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </td>
                  <td><Badge kind={m.status === "active" ? "active" : "error"}>{m.status === "active" ? "Ativo" : "Desativado"}</Badge></td>
                  <td className="nowrap">{fmtDateTime(m.last_login_at)}</td>
                  <td className="nowrap">{!locked && (
                    <div className="row">
                      <button className="btn small" onClick={() => act(() => api(`/organizations/current/members/${m.id}`, { method: "PATCH",
                        body: { status: m.status === "active" ? "disabled" : "active" } }))}>{m.status === "active" ? "Desativar" : "Reativar"}</button>
                      <button className="btn small" onClick={() => reset(m)}>Gerar senha temporária</button>
                    </div>
                  )}</td>
                </tr>
              );
            })}</tbody>
          </table></div>
        )}
      </div>
      {adding && (
        <Modal title="Adicionar membro" onClose={() => setAdding(false)} actions={
          <><button className="btn" onClick={() => setAdding(false)}>Cancelar</button><button className="btn primary" onClick={add}>Adicionar</button></>
        }>
          <div className="stack">
            <label className="field">Nome<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label className="field">E-mail<input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
            <label className="field">Papel
              <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {Object.entries(ROLES).filter(([k]) => k !== "owner" || me?.role === "owner").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            <p className="muted small">Se o e-mail ainda não tiver conta, uma senha temporária será gerada e exibida uma única vez.</p>
          </div>
        </Modal>
      )}
    </>
  );
}
