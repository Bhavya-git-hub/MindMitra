import type { Metadata } from "next";

import { TeacherDashboardView } from "@/components/teacher/dashboard-view";

export const metadata: Metadata = { title: "Overview" };

export default function TeacherOverviewPage() {
  return <TeacherDashboardView />;
}
