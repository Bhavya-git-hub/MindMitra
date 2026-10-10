import type { Metadata } from "next";

import { MoodView } from "@/components/student/trackers";

export const metadata: Metadata = { title: "Mood" };

export default function Page() {
  return <MoodView />;
}
