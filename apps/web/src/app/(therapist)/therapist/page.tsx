import { PortalOverview } from "@/components/portal/portal-overview";

const PLANNED = [
  { title: "My students", description: "Students who've chosen to share with you." },
  { title: "Schedule", description: "Your appointments in one place." },
  { title: "Session notes", description: "Private notes only you can read." },
];

export default function TherapistOverviewPage() {
  return (
    <PortalOverview
      role="therapist"
      description="Your caseload, schedule and notes will live here."
      planned={PLANNED}
    />
  );
}
