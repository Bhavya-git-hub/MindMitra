import type { Metadata } from "next";
import { Suspense } from "react";

import { NewReferralView } from "@/components/teacher/referrals-views";

export const metadata: Metadata = { title: "Refer a student" };

export default function Page() {
  return (
    <Suspense>
      <NewReferralView />
    </Suspense>
  );
}
