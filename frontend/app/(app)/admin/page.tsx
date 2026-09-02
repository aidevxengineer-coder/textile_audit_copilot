import { AdminDashboard } from "@/components/admin/admin-dashboard";
import styles from "@/components/admin/admin-dashboard.module.css";
import { getAdminScreenData, requireServerUser } from "@/lib/server-api";

export default async function AdminPage() {
  await requireServerUser("admin");
  const data = await getAdminScreenData();

  return (
    <div className={`page-shell ${styles.pageShell}`}>
      <header className={styles.pageHeader}>
        <div className={styles.headerCopy}>
          <p>Administration</p>
          <h1>Operations overview</h1>
          <p>Monitor knowledge readiness, pipeline health, connected tools, and protected activity from one clear dashboard.</p>
        </div>
        <div className={styles.headerStatus}>
          <strong><i /> Secure workspace online</strong>
          <small>Live operational data</small>
        </div>
      </header>
      <AdminDashboard {...data} />
    </div>
  );
}
