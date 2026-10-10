"use client";

import * as React from "react";

import { DataView } from "@/components/student/data-view";
import type { GroupRef } from "@/lib/api/teacher-api";
import type { WindowWeeks } from "@/lib/api/teacher-schemas";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

import { AnalyticsPanel } from "./analytics-panel";
import { ReportActions } from "./report-actions";
import { PrivacyNote, WindowTabs } from "./shared";

/** Window picker, figures and report actions for one class or the teacher's department. */
export function GroupAnalytics({ group }: { group: GroupRef }) {
  const api = useTeacherApi();
  const [weeks, setWeeks] = React.useState<WindowWeeks>(8);
  const data = useQuery(`analytics-${group.kind}-${group.id}-${weeks}`, async () =>
    group.kind === "class"
      ? (await api.classAnalytics(group.id, weeks)).analytics
      : (await api.departmentAnalytics(group.id, weeks)).analytics,
  );

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <WindowTabs value={weeks} onChange={setWeeks} />
        <ReportActions group={group} weeks={weeks} />
      </div>
      <PrivacyNote />
      <DataView query={data}>{(analytics) => <AnalyticsPanel analytics={analytics} />}</DataView>
    </>
  );
}
