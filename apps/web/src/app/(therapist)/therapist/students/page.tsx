import type { Metadata } from "next";

import { StudentsView } from "@/components/therapist/students-views";

export const metadata: Metadata = { title: "My students" };

export default function Page() {
  return <StudentsView />;
}
