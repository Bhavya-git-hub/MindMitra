import type { Metadata } from "next";

import { TrendsView } from "@/components/teacher/trends-view";

export const metadata: Metadata = { title: "Wellness trends" };

export default function Page() {
  return <TrendsView />;
}
