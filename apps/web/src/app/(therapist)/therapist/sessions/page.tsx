import type { Metadata } from "next";

import { SessionsView } from "@/components/therapist/sessions-views";

export const metadata: Metadata = { title: "Sessions" };

export default function Page() {
  return <SessionsView />;
}
