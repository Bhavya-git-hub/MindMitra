import type { Metadata } from "next";

import { ReferralsView } from "@/components/teacher/referrals-views";

export const metadata: Metadata = { title: "Referrals" };

export default function Page() {
  return <ReferralsView />;
}
