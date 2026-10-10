/**
 * Navigation per portal. Pages that are not built yet are listed with `soon: true` so the
 * shell shows the shape of each portal without linking to missing routes. This is menu
 * structure only; the API decides what each role may actually do.
 */
import {
  Activity,
  BadgeCheck,
  BellRing,
  BookOpen,
  CalendarClock,
  CalendarDays,
  ClipboardList,
  GraduationCap,
  HeartHandshake,
  Inbox,
  LayoutDashboard,
  LifeBuoy,
  LineChart,
  ListChecks,
  Lock,
  MessageCircle,
  MessageCircleHeart,
  MessageSquareHeart,
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
    { label: "Ask a teacher", href: "/student/teacher-support", icon: MessageSquareHeart },
    { label: "Resources", href: "/student/resources", icon: BookOpen },
    { label: "Privacy", href: "/student/privacy", icon: Lock },
    { label: "Urgent support", href: "/student/emergency", icon: LifeBuoy },
    account("student"),
  ],
  therapist: [
    overview("therapist"),
    { label: "My students", href: "/therapist/students", icon: Users },
    { label: "Appointments", href: "/therapist/appointments", icon: CalendarDays },
    { label: "Availability", href: "/therapist/availability", icon: CalendarClock },
    { label: "Sessions", href: "/therapist/sessions", icon: ClipboardList },
    { label: "Risk alerts", href: "/therapist/alerts", icon: BellRing },
    { label: "Follow-ups", href: "/therapist/follow-ups", icon: ListChecks },
    { label: "Messages", href: "/therapist/messages", icon: MessageCircle },
    { label: "Referrals", href: "/therapist/referrals", icon: HeartHandshake },
    { label: "Profile", href: "/therapist/profile", icon: BadgeCheck },
    account("therapist"),
  ],
  teacher: [
    overview("teacher"),
    { label: "Classes", href: "/teacher/classes", icon: GraduationCap },
    { label: "Wellness trends", href: "/teacher/trends", icon: LineChart },
    { label: "Referrals", href: "/teacher/referrals", icon: HeartHandshake },
    { label: "Student requests", href: "/teacher/support-requests", icon: Inbox },
    { label: "Resources", href: "/teacher/resources", icon: BookOpen },
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
