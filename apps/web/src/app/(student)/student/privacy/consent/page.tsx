import type { Metadata } from "next";

import { ConsentView } from "@/components/student/privacy-views";

export const metadata: Metadata = { title: "Consent" };

export default function Page() {
  return <ConsentView />;
}
