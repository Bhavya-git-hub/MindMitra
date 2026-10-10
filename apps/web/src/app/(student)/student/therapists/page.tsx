import type { Metadata } from "next";

import { TherapistSearchView } from "@/components/student/care-views";

export const metadata: Metadata = { title: "Find a therapist" };

export default function Page() {
  return <TherapistSearchView />;
}
