import { PortalOverview } from "@/components/portal/portal-overview";

const PLANNED = [
  { title: "Class insights", description: "Anonymous, aggregated patterns for your classes." },
  {
    title: "Support referrals",
    description: "Ask the counselling team to reach out to a student.",
  },
];

export default function TeacherOverviewPage() {
  return (
    <PortalOverview
      role="teacher"
      description="Class-level wellbeing signals and a simple way to refer a student for support. You never see individual conversations."
      planned={PLANNED}
    />
  );
}
