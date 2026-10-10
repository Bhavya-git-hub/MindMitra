import type { Metadata } from "next";

import { AcademicsView } from "@/components/admin/academics-views";

export const metadata: Metadata = { title: "Departments and courses" };

export default function Page() {
  return <AcademicsView />;
}
