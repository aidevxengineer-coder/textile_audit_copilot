import { ReportView } from "@/components/report/report-view";
import { getServerReport, requireServerUser } from "@/lib/server-api";

export default async function ReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  await requireServerUser();
  const { reportId } = await params;
  const report = await getServerReport(reportId);
  return <ReportView report={report} />;
}
