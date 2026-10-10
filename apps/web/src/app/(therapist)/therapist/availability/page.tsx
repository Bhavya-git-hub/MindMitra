import type { Metadata } from "next";

import { AvailabilityView } from "@/components/therapist/availability-view";

export const metadata: Metadata = { title: "Availability" };

export default function Page() {
  return <AvailabilityView />;
}
