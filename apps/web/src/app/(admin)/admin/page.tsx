import { PortalOverview } from "@/components/portal/portal-overview";

const PLANNED = [
  { title: "People", description: "Invite staff and manage accounts." },
  { title: "Institution", description: "Departments, contacts and policies." },
  { title: "Audit log", description: "A record of who did what, and when." },
  { title: "Safety settings", description: "Escalation contacts and thresholds." },
];

export default function AdministratorOverviewPage() {
  return (
    <PortalOverview
      role="administrator"
      description="Manage people, institution settings and safety configuration. You can't read student content."
      planned={PLANNED}
    />
  );
}
