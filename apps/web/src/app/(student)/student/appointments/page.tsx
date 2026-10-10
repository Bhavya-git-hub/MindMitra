import type { Metadata } from "next";

import { AppointmentsView } from "@/components/student/care-views";

export const metadata: Metadata = { title: "Appointments" };

export default function Page() {
  return <AppointmentsView />;
}
