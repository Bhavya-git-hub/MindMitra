import type { Metadata } from "next";

import { OversightView } from "@/components/admin/insights-views";

export const metadata: Metadata = { title: "Appointment oversight" };

export default function Page() {
  return <OversightView />;
}
