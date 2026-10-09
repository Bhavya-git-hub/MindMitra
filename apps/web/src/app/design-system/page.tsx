import { notFound } from "next/navigation";

import { Showcase } from "@/components/design-system/showcase";
import { designSystemEnabled } from "@/lib/env";

export const metadata = { title: "Design system", robots: { index: false } };

/** Living style guide. Development only unless ENABLE_DESIGN_SYSTEM=true. */
export default function DesignSystemPage() {
  if (!designSystemEnabled()) notFound();
  return <Showcase />;
}
