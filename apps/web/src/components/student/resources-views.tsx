"use client";

import { BookOpen, ExternalLink } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { NativeSelect } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Resource, ResourceDetail as ResourceDetailData } from "@/lib/api/student-schemas";
import { useQuery } from "@/lib/hooks/use-query";
import { useStudentApi } from "@/lib/hooks/use-student-api";
import { RESOURCE_TYPE_LABELS } from "@/lib/student-options";

/** Where a resource library gets its items and where each item's page lives. */
export interface ResourceSource {
  cacheKey: string;
  basePath: string;
  title: string;
  description: string;
  list: () => Promise<Resource[]>;
  get: (id: string) => Promise<ResourceDetailData>;
}

export function ResourceLibrary({ source }: { source: ResourceSource }) {
  const all = useQuery(source.cacheKey, () => source.list());
  const [text, setText] = React.useState("");
  const [type, setType] = React.useState("");

  return (
    <>
      <PageHeader title={source.title} description={source.description} />
      <DataView query={all}>
        {(items) => {
          const needle = text.trim().toLowerCase();
          const shown = items.filter(
            (r) =>
              (!type || r.resource_type === type) &&
              (!needle ||
                r.title.toLowerCase().includes(needle) ||
                r.summary.toLowerCase().includes(needle) ||
                r.tags.some((t) => t.toLowerCase().includes(needle))),
          );
          const types = [...new Set(items.map((r) => r.resource_type))];
          return (
            <>
              <form
                role="search"
                aria-label="Find a resource"
                onSubmit={(e) => e.preventDefault()}
                className="grid gap-4 rounded-xl border bg-card p-4 sm:grid-cols-2"
              >
                <div className="space-y-2">
                  <Label htmlFor="r-search">Search</Label>
                  <Input
                    id="r-search"
                    type="search"
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="Sleep, exams, breathing…"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="r-type">Type</Label>
                  <NativeSelect id="r-type" value={type} onChange={(e) => setType(e.target.value)}>
                    <option value="">All types</option>
                    {types.map((t) => (
                      <option key={t} value={t}>
                        {RESOURCE_TYPE_LABELS[t] ?? t}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              </form>
              <p role="status" className="text-sm text-muted-foreground">
                {shown.length} resource{shown.length === 1 ? "" : "s"} shown
              </p>
              {shown.length === 0 ? (
                <EmptyState
                  icon={BookOpen}
                  title="Nothing matches"
                  description="Try a different word."
                />
              ) : (
                <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {shown.map((r) => (
                    <li key={r.id} className="flex flex-col gap-2 rounded-xl border bg-card p-4">
                      <Badge variant="secondary" className="w-fit">
                        {RESOURCE_TYPE_LABELS[r.resource_type] ?? r.resource_type}
                        {r.duration_minutes ? ` · ${r.duration_minutes} min` : ""}
                      </Badge>
                      <h3 className="font-medium">
                        <Link
                          href={`${source.basePath}/${r.id}`}
                          className="underline-offset-4 hover:underline"
                        >
                          {r.title}
                        </Link>
                      </h3>
                      <p className="text-sm text-muted-foreground">{r.summary}</p>
                    </li>
                  ))}
                </ul>
              )}
            </>
          );
        }}
      </DataView>
    </>
  );
}

export function ResourceDetail({ id, source }: { id: string; source: ResourceSource }) {
  const resource = useQuery(`${source.cacheKey}-${id}`, () => source.get(id));
  return (
    <DataView query={resource}>
      {(r) => (
        <>
          <PageHeader
            title={r.title}
            description={r.summary}
            actions={
              <Button asChild variant="ghost">
                <Link href={source.basePath}>All resources</Link>
              </Button>
            }
          />
          <SectionCard
            title={RESOURCE_TYPE_LABELS[r.resource_type] ?? r.resource_type}
            description={r.duration_minutes ? `About ${r.duration_minutes} minutes` : undefined}
          >
            <div className="space-y-4">
              {r.body && <p className="max-w-prose whitespace-pre-line">{r.body}</p>}
              {r.url && /^https?:\/\//i.test(r.url) && (
                <Button asChild variant="outline">
                  <a href={r.url} target="_blank" rel="noopener noreferrer">
                    Open the full resource
                    <ExternalLink aria-hidden="true" />
                    <span className="sr-only">(opens in a new tab)</span>
                  </a>
                </Button>
              )}
              {r.tags.length > 0 && (
                <p className="flex flex-wrap gap-1.5">
                  {r.tags.map((t) => (
                    <Badge key={t} variant="outline">
                      {t}
                    </Badge>
                  ))}
                </p>
              )}
            </div>
          </SectionCard>
        </>
      )}
    </DataView>
  );
}

function useStudentResourceSource(): ResourceSource {
  const api = useStudentApi();
  return React.useMemo(
    () => ({
      cacheKey: "resources",
      basePath: "/student/resources",
      title: "Resources",
      description: "Articles, exercises and campus services chosen to help you feel well.",
      list: () => api.resources(),
      get: (id: string) => api.resource(id),
    }),
    [api],
  );
}

export function ResourcesView() {
  return <ResourceLibrary source={useStudentResourceSource()} />;
}

export function ResourceDetailView({ id }: { id: string }) {
  return <ResourceDetail id={id} source={useStudentResourceSource()} />;
}
