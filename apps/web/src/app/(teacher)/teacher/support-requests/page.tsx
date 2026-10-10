import type { Metadata } from "next";

import { SupportRequestsView } from "@/components/teacher/support-requests-view";

export const metadata: Metadata = { title: "Student requests" };

export default function Page() {
  return <SupportRequestsView />;
}
