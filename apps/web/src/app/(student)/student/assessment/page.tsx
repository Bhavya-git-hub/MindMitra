import type { Metadata } from "next";

import { AssessmentView } from "@/components/student/wellness-views";

export const metadata: Metadata = { title: "Wellbeing check" };

export default function Page() {
  return <AssessmentView />;
}
