/** Synthetic service-analytics payloads for the administrator tests (counts only, no people). */
import type { EngagementGroup, ServiceAnalytics } from "@/lib/api/admin-schemas";

const hidden = (key: string): EngagementGroup => ({
  key,
  suppressed: true,
  suggestions: null,
  viewed: null,
  completed: null,
  dismissed: null,
  helpful: null,
  not_helpful: null,
});

export const engagementGroup = (
  key: string,
  extra: Partial<EngagementGroup> = {},
): EngagementGroup => ({
  key,
  suppressed: false,
  suggestions: 40,
  viewed: 25,
  completed: 15,
  dismissed: 5,
  helpful: 10,
  not_helpful: null,
  ...extra,
});

export const suppressedGroup = hidden;

const noShare = { state: "hidden", percent: null } as const;

export const serviceAnalytics = (extra: Partial<ServiceAnalytics> = {}): ServiceAnalytics => ({
  window_weeks: 8,
  window_start: "2026-09-14",
  window_end: "2026-10-04",
  usage: {
    weekly: [
      {
        week_start: "2026-09-14",
        check_ins: 120,
        active_students: 45,
        companion_messages: 310,
        therapist_messages: 88,
        sign_ins: 200,
      },
      {
        week_start: "2026-09-21",
        check_ins: null,
        active_students: null,
        companion_messages: 0,
        therapist_messages: null,
        sign_ins: 160,
      },
    ],
    totals: {
      check_ins: 120,
      active_students: 47,
      companion_messages: 310,
      therapist_messages: null,
      sign_ins: 360,
    },
  },
  utilisation: {
    overall: {
      capacity_hours: 17.3,
      booked_hours: 9.7,
      utilisation_percent: 55,
      no_show_share: { state: "few", percent: null },
      cancellation_share: { state: "shown", percent: 35 },
    },
    weekly: [
      {
        week_start: "2026-09-14",
        capacity_hours: 12.3,
        booked_hours: 7.7,
        utilisation_percent: 60,
      },
      {
        week_start: "2026-09-21",
        capacity_hours: 5,
        booked_hours: null,
        utilisation_percent: null,
      },
    ],
    by_mode: [
      {
        mode: "video",
        capacity_hours: 15,
        booked_hours: 8,
        utilisation_percent: 55,
        no_show_share: noShare,
        cancellation_share: { state: "most", percent: null },
      },
      {
        mode: "in_person",
        capacity_hours: 0,
        booked_hours: 0,
        utilisation_percent: null,
        no_show_share: noShare,
        cancellation_share: noShare,
      },
      {
        mode: "phone",
        capacity_hours: 2.3,
        booked_hours: null,
        utilisation_percent: null,
        no_show_share: noShare,
        cancellation_share: noShare,
      },
    ],
  },
  engagement: {
    by_source: [
      engagementGroup("rule", { suggestions: 120, completed: 30 }),
      hidden("model"),
      hidden("therapist"),
    ],
    by_problem_area: [
      engagementGroup("stress", { suggestions: 60, completed: 20, helpful: 15 }),
      engagementGroup("sleep_disruption", { suggestions: 25, completed: null, helpful: null }),
      hidden("academic_burnout"),
      hidden("mood"),
      hidden("other"),
    ],
    completion_share: { state: "shown", percent: 45 },
    helpful_share: { state: "hidden", percent: null },
    top_interventions: [
      { intervention_key: "box_breathing", students: 15 },
      { intervention_key: "short_walk", students: 5 },
    ],
  },
  disclaimer: "Counts and averages over many people. Nothing here describes an individual.",
  generated_at: "2026-10-10T09:00:00Z",
  ...extra,
});

/** A quiet institution: nothing offered, nothing used, every group too small. */
export const quietServiceAnalytics = (): ServiceAnalytics => {
  const base = serviceAnalytics();
  return serviceAnalytics({
    usage: {
      weekly: base.usage.weekly.map((w) => ({
        week_start: w.week_start,
        check_ins: 0,
        active_students: 0,
        companion_messages: 0,
        therapist_messages: 0,
        sign_ins: 0,
      })),
      totals: {
        check_ins: 0,
        active_students: 0,
        companion_messages: 0,
        therapist_messages: 0,
        sign_ins: 0,
      },
    },
    utilisation: {
      overall: {
        capacity_hours: 0,
        booked_hours: 0,
        utilisation_percent: null,
        no_show_share: noShare,
        cancellation_share: noShare,
      },
      weekly: base.utilisation.weekly.map((w) => ({
        week_start: w.week_start,
        capacity_hours: 0,
        booked_hours: 0,
        utilisation_percent: null,
      })),
      by_mode: [],
    },
    engagement: {
      by_source: [hidden("rule"), hidden("model"), hidden("therapist")],
      by_problem_area: [hidden("stress"), hidden("other")],
      completion_share: noShare,
      helpful_share: noShare,
      top_interventions: [],
    },
  });
};
