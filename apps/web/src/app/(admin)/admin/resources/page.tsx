import type { Metadata } from "next";

import { AdminResourcesView } from "@/components/admin/resources-views";

export const metadata: Metadata = { title: "Resources" };

export default function Page() {
  return <AdminResourcesView />;
}
