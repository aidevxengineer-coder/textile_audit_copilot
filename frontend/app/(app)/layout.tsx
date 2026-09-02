import { AppShell } from "@/components/layout/app-shell";
import { requireServerUser } from "@/lib/server-api";

export default async function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const user = await requireServerUser();
  return <AppShell user={user}>{children}</AppShell>;
}
