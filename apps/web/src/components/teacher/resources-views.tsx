"use client";

import * as React from "react";

import {
  ResourceDetail,
  ResourceLibrary,
  type ResourceSource,
} from "@/components/student/resources-views";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

function useFacultySource(): ResourceSource {
  const api = useTeacherApi();
  return React.useMemo(
    () => ({
      cacheKey: "faculty-resources",
      basePath: "/teacher/resources",
      title: "Resources for staff",
      description:
        "Guides for supporting students well and looking after yourself. Only staff see this library.",
      list: () => api.resources(),
      get: (id: string) => api.resource(id),
    }),
    [api],
  );
}

export function TeacherResourcesView() {
  return <ResourceLibrary source={useFacultySource()} />;
}

export function TeacherResourceDetailView({ id }: { id: string }) {
  return <ResourceDetail id={id} source={useFacultySource()} />;
}
