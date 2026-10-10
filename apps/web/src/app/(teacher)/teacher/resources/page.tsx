import type { Metadata } from "next";

import { TeacherResourcesView } from "@/components/teacher/resources-views";

export const metadata: Metadata = { title: "Resources for staff" };

export default function Page() {
  return <TeacherResourcesView />;
}
