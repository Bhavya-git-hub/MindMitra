import type { Metadata } from "next";

import { WellnessView } from "@/components/student/wellness-views";

export const metadata: Metadata = { title: "Wellness" };

export default function Page() {
  return <WellnessView />;
}
