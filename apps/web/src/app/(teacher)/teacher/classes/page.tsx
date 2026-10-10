import type { Metadata } from "next";

import { ClassesView } from "@/components/teacher/classes-views";

export const metadata: Metadata = { title: "Class analytics" };

export default function Page() {
  return <ClassesView />;
}
