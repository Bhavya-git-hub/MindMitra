import type { Metadata } from "next";

import { AnalyticsView } from "@/components/admin/insights-views";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return <AnalyticsView />;
}
