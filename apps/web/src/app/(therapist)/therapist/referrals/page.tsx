import type { Metadata } from "next";

import { TriageReferralsView } from "@/components/therapist/referrals-view";

export const metadata: Metadata = { title: "Referrals" };

export default function Page() {
  return <TriageReferralsView />;
}
