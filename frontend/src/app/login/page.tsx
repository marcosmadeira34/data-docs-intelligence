"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ErrorAlert } from "@/components/ui";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { refresh } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/login", { method: "POST", body: { email, password } });
      await refresh();
      const next = params.get("next");
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
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
          <h1>Entrar</h1>
          <p className="muted">Data Docs Intelligence — validação e comparação de planilhas.</p>
        </div>
        <ErrorAlert error={error} />
        <label className="field">E-mail
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">Senha
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button className="btn primary" type="submit" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
        <p className="small muted">
          Esqueceu a senha? Peça a um administrador da sua organização para gerar uma senha temporária.
          <br />
          Ainda não tem conta? <Link href="/cadastro">Cadastre seu escritório</Link>.
        </p>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
