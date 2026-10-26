"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";

export type Role = "owner" | "admin" | "analyst" | "viewer";
export type Me = {
  user: { id: string; name: string; email: string };
  organization: { id: string; name: string };
  role: Role;
  memberships: { organization_id: string; organization_name: string; role: Role }[];
};

const RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2, owner: 3 };

type Ctx = { me: Me | null; loading: boolean; refresh: () => Promise<void>; can: (min: Role) => boolean; logout: () => Promise<void> };
const SessionContext = createContext<Ctx>({ me: null, loading: true, refresh: async () => {}, can: () => false, logout: async () => {} });

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>("/me"));
    } catch {
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const onUnauthorized = () => {
      setMe(null);
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    };
    window.addEventListener("ddi:unauthorized", onUnauthorized);
    return () => window.removeEventListener("ddi:unauthorized", onUnauthorized);
  }, [router, pathname]);

  const can = useCallback((min: Role) => (me ? RANK[me.role] >= RANK[min] : false), [me]);
  const logout = useCallback(async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    setMe(null);
    router.replace("/login");
  }, [router]);

  return <SessionContext.Provider value={{ me, loading, refresh, can, logout }}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);
