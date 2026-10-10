import type { Metadata } from "next";

import { NewResourceView } from "@/components/admin/resources-views";

export const metadata: Metadata = { title: "New resource" };

export default function Page() {
  return <NewResourceView />;
}
