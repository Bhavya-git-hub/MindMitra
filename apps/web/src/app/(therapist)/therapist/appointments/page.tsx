import type { Metadata } from "next";

import { AppointmentsView } from "@/components/therapist/appointments-view";

export const metadata: Metadata = { title: "Appointments" };

export default function Page() {
  return <AppointmentsView />;
}
