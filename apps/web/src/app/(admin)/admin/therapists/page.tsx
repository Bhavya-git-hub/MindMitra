import type { Metadata } from "next";

import { VerificationView } from "@/components/admin/verification-view";

export const metadata: Metadata = { title: "Therapist verification" };

export default function Page() {
  return <VerificationView />;
}
