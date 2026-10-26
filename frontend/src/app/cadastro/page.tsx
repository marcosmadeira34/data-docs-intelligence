"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorAlert } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

export default function SignupPage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [form, setForm] = useState({ organization_name: "", name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/signup", { method: "POST", body: form });
      await refresh();
      router.replace("/");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <form className="card auth-card stack" onSubmit={submit}>
        <div>
          <h1>Cadastrar escritório</h1>
          <p className="muted">Crie a organização e o usuário proprietário. O plano de avaliação é ativado automaticamente.</p>
        </div>
        <ErrorAlert error={error} />
        <label className="field">Nome do escritório ou BPO
          <input required minLength={2} value={form.organization_name} onChange={set("organization_name")} />
        </label>
        <label className="field">Seu nome
          <input required minLength={2} value={form.name} onChange={set("name")} />
        </label>
        <label className="field">E-mail
          <input type="email" autoComplete="username" required value={form.email} onChange={set("email")} />
        </label>
        <label className="field">Senha (mínimo 10 caracteres, combinando letras e números/símbolos)
          <input type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={set("password")} />
        </label>
        <button className="btn primary" type="submit" disabled={busy}>{busy ? "Criando…" : "Criar conta"}</button>
        <p className="small muted">Já tem conta? <Link href="/login">Entrar</Link>.</p>
      </form>
    </div>
  );
}
