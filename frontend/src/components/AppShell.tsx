"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { ROLES } from "@/lib/format";
import { Role, useSession } from "@/lib/session";
import { Spinner } from "./ui";

const NAV: { href: string; label: string; min?: Role }[] = [
  { href: "/", label: "Painel" },
  { href: "/empresas", label: "Empresas atendidas" },
  { href: "/arquivos", label: "Arquivos" },
  { href: "/perfis", label: "Perfis de layout" },
  { href: "/regras", label: "Regras de validação" },
  { href: "/execucoes", label: "Execuções" },
  { href: "/comparacoes", label: "Comparações" },
  { href: "/usuarios", label: "Usuários e permissões", min: "admin" },
  { href: "/auditoria", label: "Auditoria", min: "admin" },
  { href: "/conta", label: "Minha conta e plano" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading, can, logout, refresh } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !me) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, me, router, pathname]);

  if (loading || !me) {
    return (
      <div className="auth-page">
        <Spinner />
      </div>
    );
  }

  const switchOrg = async (orgId: string) => {
    await api("/auth/switch-organization", { method: "POST", body: { organization_id: orgId } });
    await refresh();
    router.push("/");
  };

  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Navegação principal">
        <div className="brand">
          Data Docs Intelligence
          <small>{me.organization.name}</small>
        </div>
        {NAV.filter((n) => !n.min || can(n.min)).map((n) => {
          const active = n.href === "/" ? pathname === "/" : pathname.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href} className={active ? "active" : ""}>
              {n.label}
            </Link>
          );
        })}
        <div className="spacer" />
        <div className="user">
          <div>{me.user.name}</div>
          <div>{ROLES[me.role]}</div>
          {me.memberships.length > 1 && (
            <select style={{ marginTop: 6, width: "100%" }} value={me.organization.id} onChange={(e) => switchOrg(e.target.value)}
              aria-label="Trocar organização">
              {me.memberships.map((m) => (
                <option key={m.organization_id} value={m.organization_id}>{m.organization_name}</option>
              ))}
            </select>
          )}
          <button className="btn small" style={{ marginTop: 8 }} onClick={logout}>Sair</button>
        </div>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
