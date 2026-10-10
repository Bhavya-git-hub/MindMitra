import type { Metadata } from "next";

import { DashboardView } from "@/components/therapist/dashboard-view";

export const metadata: Metadata = { title: "Overview" };

export default function Page() {
  return <DashboardView />;
}
