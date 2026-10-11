import type { Metadata } from "next";

import { AnalyticsView } from "@/components/therapist/analytics-view";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return <AnalyticsView />;
}
