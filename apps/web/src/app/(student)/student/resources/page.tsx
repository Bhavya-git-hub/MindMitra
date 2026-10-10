import type { Metadata } from "next";

import { ResourcesView } from "@/components/student/resources-views";

export const metadata: Metadata = { title: "Resources" };

export default function Page() {
  return <ResourcesView />;
}
