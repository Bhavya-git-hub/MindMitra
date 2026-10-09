import { PortalOverview } from "@/components/portal/portal-overview";

const PLANNED = [
  { title: "Daily check-in", description: "A short, private note on how you're feeling." },
  {
    title: "Companion chat",
    description: "Supportive conversation, any time. It's an AI companion, not a clinician.",
  },
  { title: "Appointments", description: "Book and manage time with a counsellor." },
  { title: "Resources", description: "Calming exercises and guides, picked for students." },
];

export default function StudentOverviewPage() {
  return (
    <PortalOverview
      role="student"
      description="A quiet place to check in with yourself. The tools below are being built one at a time."
      planned={PLANNED}
    />
  );
}
