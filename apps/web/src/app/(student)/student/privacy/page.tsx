import type { Metadata } from "next";

import { PrivacyCenterView } from "@/components/student/privacy-views";

export const metadata: Metadata = { title: "Privacy" };

export default function Page() {
  return <PrivacyCenterView />;
}
