import type { Metadata } from "next";

import { SleepView } from "@/components/student/trackers";

export const metadata: Metadata = { title: "Sleep" };

export default function Page() {
  return <SleepView />;
}
