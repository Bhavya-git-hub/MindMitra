/**
 * Navigation per portal. Pages that are not built yet are listed with `soon: true` so the
 * shell shows the shape of each portal without linking to missing routes. This is menu
 * structure only; the API decides what each role may actually do.
 */
import {
  Activity,
  BookOpen,
  CalendarDays,
  ClipboardList,
  HeartHandshake,
  LayoutDashboard,
  LifeBuoy,
  LineChart,
  Lock,
  MessageCircle,
  MessageCircleHeart,
  NotebookPen,
  ScrollText,
  Settings2,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Target,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

import { PORTAL_PATHS, type Role } from "@/lib/auth/roles";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Not built yet: shown disabled with a "Soon" badge and never linked. */
  soon?: boolean;
  /** Other paths that belong under this item, so it stays highlighted on them. */
  also?: string[];
}

const overview = (role: Role): NavItem => ({
  label: "Overview",
  href: PORTAL_PATHS[role],
  icon: LayoutDashboard,
});

const account = (role: Role): NavItem => ({
  label: "Account",
  href: `${PORTAL_PATHS[role]}/account`,
  icon: UserRound,
});

export const NAVIGATION: Record<Role, NavItem[]> = {
  student: [
    overview("student"),
    { label: "Daily check-in", href: "/student/check-in", icon: NotebookPen },
    {
      label: "Wellness",
      href: "/student/wellness",
      icon: Activity,
      also: [
        "/student/mood",
        "/student/stress",
        "/student/sleep",
        "/student/assessment",
        "/student/trends",
      ],
    },
    { label: "Goals", href: "/student/goals", icon: Target },
    { label: "Suggestions", href: "/student/recommendations", icon: Sparkles },
    { label: "Companion", href: "/student/assistant", icon: MessageCircleHeart },
    { label: "Therapists", href: "/student/therapists", icon: Stethoscope },
    { label: "Appointments", href: "/student/appointments", icon: CalendarDays },
    { label: "Messages", href: "/student/messages", icon: MessageCircle },
    { label: "Resources", href: "/student/resources", icon: BookOpen },
    { label: "Privacy", href: "/student/privacy", icon: Lock },
    { label: "Urgent support", href: "/student/emergency", icon: LifeBuoy },
    account("student"),
  ],
  therapist: [
    overview("therapist"),
    { label: "My students", href: "/therapist/students", icon: Users, soon: true },
    { label: "Schedule", href: "/therapist/schedule", icon: CalendarDays, soon: true },
    { label: "Session notes", href: "/therapist/notes", icon: ClipboardList, soon: true },
    account("therapist"),
  ],
  teacher: [
    overview("teacher"),
    { label: "Class insights", href: "/teacher/insights", icon: LineChart, soon: true },
    { label: "Support referrals", href: "/teacher/referrals", icon: HeartHandshake, soon: true },
    account("teacher"),
  ],
  administrator: [
    overview("administrator"),
    { label: "People", href: "/admin/users", icon: Users, soon: true },
    { label: "Institution", href: "/admin/institution", icon: Settings2, soon: true },
    { label: "Audit log", href: "/admin/audit", icon: ScrollText, soon: true },
    { label: "Safety settings", href: "/admin/safety", icon: ShieldCheck, soon: true },
    account("administrator"),
  ],
};

/** The nav item whose href is the longest prefix of `pathname` (so /student/account wins). */
export function activeHref(items: NavItem[], pathname: string): string | null {
  let best: string | null = null;
  let bestLength = 0;
  for (const { href, soon, also } of items) {
    if (soon) continue;
    for (const prefix of [href, ...(also ?? [])]) {
      const matches = pathname === prefix || pathname.startsWith(`${prefix}/`);
      if (matches && prefix.length > bestLength) {
        best = href;
        bestLength = prefix.length;
      }
    }
  }
  return best;
}
