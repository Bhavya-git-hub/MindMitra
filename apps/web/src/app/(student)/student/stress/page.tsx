import type { Metadata } from "next";

import { StressView } from "@/components/student/trackers";

export const metadata: Metadata = { title: "Stress" };

export default function Page() {
  return <StressView />;
}
