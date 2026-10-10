import type { Metadata } from "next";

import { FollowUpsView } from "@/components/therapist/follow-ups-view";

export const metadata: Metadata = { title: "Follow-ups" };

export default function Page() {
  return <FollowUpsView />;
}
