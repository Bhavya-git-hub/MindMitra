import type { Metadata } from "next";

import { EmergencyView } from "@/components/student/emergency-view";

export const metadata: Metadata = { title: "Urgent support" };

export default function Page() {
  return <EmergencyView />;
}
