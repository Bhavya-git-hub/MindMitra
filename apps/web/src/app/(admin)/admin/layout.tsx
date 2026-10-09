import type { Metadata } from "next";
import * as React from "react";

import { PortalLayout } from "@/components/auth/portal-layout";

export const metadata: Metadata = {
  title: { default: "Administrator", template: "%s · Administrator · MindMitra" },
};

export default function AdministratorLayout({ children }: { children: React.ReactNode }) {
  return <PortalLayout role="administrator">{children}</PortalLayout>;
}
