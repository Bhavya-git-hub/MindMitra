import type { Metadata } from "next";

import { RecommendationsView } from "@/components/student/recommendations-view";

export const metadata: Metadata = { title: "Suggestions" };

export default function Page() {
  return <RecommendationsView />;
}
