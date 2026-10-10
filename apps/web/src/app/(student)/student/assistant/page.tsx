import type { Metadata } from "next";

import { CompanionHomeView } from "@/components/student/companion-views";

export const metadata: Metadata = { title: "Companion" };

export default function Page() {
  return <CompanionHomeView />;
}
