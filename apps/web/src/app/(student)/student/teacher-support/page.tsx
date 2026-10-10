import type { Metadata } from "next";

import { TeacherSupportView } from "@/components/student/teacher-support-view";

export const metadata: Metadata = { title: "Ask a teacher" };

export default function Page() {
  return <TeacherSupportView />;
}
