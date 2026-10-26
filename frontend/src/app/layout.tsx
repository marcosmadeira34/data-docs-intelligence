import type { Metadata } from "next";
import "./globals.css";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  title: "Data Docs Intelligence",
  description: "Validação, comparação e padronização de planilhas para escritórios contábeis e BPOs financeiros.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
