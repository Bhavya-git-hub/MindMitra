import type { Metadata } from "next";

import { DashboardView } from "@/components/student/dashboard-view";

export const metadata: Metadata = { title: "Overview" };

export default function StudentOverviewPage() {
  return <DashboardView />;
}
