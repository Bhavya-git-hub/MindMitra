import type { Metadata } from "next";
import * as React from "react";

import { PortalLayout } from "@/components/auth/portal-layout";

export const metadata: Metadata = {
  title: { default: "Therapist", template: "%s · Therapist · MindMitra" },
};

export default function TherapistLayout({ children }: { children: React.ReactNode }) {
  return <PortalLayout role="therapist">{children}</PortalLayout>;
}
