import type { Metadata } from "next";
import * as React from "react";

import { PortalLayout } from "@/components/auth/portal-layout";

export const metadata: Metadata = {
  title: { default: "Teacher", template: "%s · Teacher · MindMitra" },
};

export default function TeacherLayout({ children }: { children: React.ReactNode }) {
  return <PortalLayout role="teacher">{children}</PortalLayout>;
}
