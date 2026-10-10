import type { Metadata } from "next";

import { TrendsView } from "@/components/student/wellness-views";

export const metadata: Metadata = { title: "Your trends" };

export default function Page() {
  return <TrendsView />;
}
