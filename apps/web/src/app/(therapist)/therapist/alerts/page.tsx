import type { Metadata } from "next";

import { AlertsView } from "@/components/therapist/alerts-view";

export const metadata: Metadata = { title: "Risk alerts" };

export default function Page() {
  return <AlertsView />;
}
