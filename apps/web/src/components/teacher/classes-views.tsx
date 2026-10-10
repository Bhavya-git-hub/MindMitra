"use client";

import { GraduationCap, HeartHandshake } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { Button } from "@/components/ui/button";
import { useQuery } from "@/lib/hooks/use-query";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

import { GroupAnalytics } from "./group-view";

export function ClassesView() {
  const api = useTeacherApi();
  const classes = useQuery("teacher-classes", () => api.classes());
  return (
    <>
      <PageHeader
        title="Class analytics"
        description="Choose a class to see anonymous wellbeing and stress trends for the students in it."
      />
      <DataView query={classes}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              icon={GraduationCap}
              title="No classes yet"
              description="Classes you teach appear here once they are set up for this term."
            />
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((c) => (
                <li key={c.id} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
                  <p className="text-sm text-muted-foreground">
                    {c.code} · {c.term}
                  </p>
                  <h2 className="font-medium">
                    <Link
                      href={`/teacher/classes/${c.id}`}
                      className="underline-offset-4 hover:underline"
                    >
                      {c.title}
                    </Link>
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {c.department_name} · {c.enrolled} enrolled
                  </p>
                </li>
              ))}
            </ul>
          )
        }
      </DataView>
    </>
  );
}

export function ClassDetailView({ id }: { id: string }) {
  const api = useTeacherApi();
  const cls = useQuery(`teacher-class-${id}`, () => api.class(id));
  return (
    <DataView query={cls}>
      {(c) => (
        <>
          <PageHeader
            title={c.title}
            description={`${c.code} · ${c.term} · ${c.enrolled} enrolled`}
            actions={
              <>
                <Button asChild variant="ghost" size="sm">
                  <Link href="/teacher/classes">All classes</Link>
                </Button>
                <Button asChild size="sm">
                  <Link href={`/teacher/referrals/new?class=${c.id}`}>
                    <HeartHandshake aria-hidden="true" />
                    Refer a student
                  </Link>
                </Button>
              </>
            }
          />
          <GroupAnalytics group={{ kind: "class", id: c.id }} />
        </>
      )}
    </DataView>
  );
}
