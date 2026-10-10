import type { Metadata } from "next";

import { AssistantView } from "@/components/student/assistant-view";

export const metadata: Metadata = { title: "Companion" };

export default function Page() {
  return <AssistantView />;
}
