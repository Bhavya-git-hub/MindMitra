import type { Metadata } from "next";
import * as React from "react";

import { PortalLayout } from "@/components/auth/portal-layout";

export const metadata: Metadata = {
  title: { default: "Student", template: "%s · Student · MindMitra" },
};

export default function StudentLayout({ children }: { children: React.ReactNode }) {
  return <PortalLayout role="student">{children}</PortalLayout>;
}
