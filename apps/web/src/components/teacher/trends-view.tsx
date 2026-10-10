"use client";

import { PageHeader } from "@/components/layout/page-header";
import { DataView } from "@/components/student/data-view";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

import { GroupAnalytics } from "./group-view";

/** Department-level trends. A teacher is authorized for their own department only. */
export function TrendsView() {
  const api = useTeacherApi();
  const dash = useQuery("teacher-dashboard", () => api.dashboard());
  return (
    <>
      <PageHeader
        title="Wellness trends"
        description="Anonymous wellbeing, academic-stress and burnout-sign trends across your department."
      />
      <DataView query={dash}>
        {(d) => (
          <>
            <p className="text-sm text-muted-foreground">
              Showing {d.teacher.department_name}. You can see your own department only.
            </p>
            <GroupAnalytics group={{ kind: "department", id: d.teacher.department_id }} />
          </>
        )}
      </DataView>
    </>
  );
}
