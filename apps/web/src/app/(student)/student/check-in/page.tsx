import type { Metadata } from "next";

import { CheckInView } from "@/components/student/check-in-view";

export const metadata: Metadata = { title: "Daily check-in" };

export default function Page() {
  return <CheckInView />;
}
