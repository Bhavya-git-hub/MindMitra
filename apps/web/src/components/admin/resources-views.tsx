"use client";

import { BookOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { useModal } from "@/components/providers/modal-provider";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { SegmentedTabs } from "@/components/therapist/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ResourceInput } from "@/lib/api/admin-api";
import { RESOURCE_TYPES, type AdminResource } from "@/lib/api/admin-schemas";
import { describeError } from "@/lib/api/errors";
import { formatShortDate, titleCase } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";
import { notify } from "@/lib/toast";

import { Field, SearchBox, splitList, useDebounced } from "./shared";

type Filter = "all" | "published" | "drafts" | "global";

export function AdminResourcesView() {
  const api = useAdminApi();
  const modal = useModal();
  const [filter, setFilter] = React.useState<Filter>("all");
  const [type, setType] = React.useState("");
  const [search, setSearch] = React.useState("");
  const q = useDebounced(search.trim());
  const list = useQuery(`admin-resources-${filter}-${type}-${q}`, () =>
    api.resources({
      resource_type: type || undefined,
      q: q || undefined,
      published: filter === "published" ? true : filter === "drafts" ? false : undefined,
      source: filter === "global" ? "global" : undefined,
    }),
  );

  async function act(label: string, run: () => Promise<unknown>) {
    try {
      await run();
      notify.success(label);
      void list.reload();
    } catch (e) {
      notify.error("That didn't work", describeError(e));
    }
  }

  async function remove(r: AdminResource) {
    const ok = await modal.confirm({
      title: `Delete “${r.title}”?`,
      description: "Students who were shown it will no longer see it.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (ok) await act("Resource deleted", () => api.deleteResource(r.id));
  }

  return (
    <>
      <PageHeader
        title="Resources"
        description="The self-help library students and staff can read. Nothing is shown until you publish it."
        actions={
          <Button asChild>
            <Link href="/admin/resources/new">
              <Plus aria-hidden="true" />
              New resource
            </Link>
          </Button>
        }
      />
      <SegmentedTabs
        label="Show"
        value={filter}
        onChange={setFilter}
        options={[
          { value: "all", label: "All" },
          { value: "published", label: "Published" },
          { value: "drafts", label: "Drafts" },
          { value: "global", label: "Shipped with MindMitra" },
        ]}
      />
      <div className="flex flex-wrap items-end gap-3">
        <SearchBox label="Search resources" value={search} onChange={setSearch} />
        <NativeSelect
          aria-label="Type"
          className="w-44"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="">Any type</option>
          {RESOURCE_TYPES.map((t) => (
            <option key={t} value={t}>
              {titleCase(t)}
            </option>
          ))}
        </NativeSelect>
      </div>
      <DataView query={list}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState
              icon={BookOpen}
              title="Nothing here yet"
              description="Add a resource, or change the filters."
            />
          ) : (
            <SectionCard title={`${rows.length} resource${rows.length === 1 ? "" : "s"}`}>
              <ul className="divide-y">
                {rows.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-start justify-between gap-3 py-4">
                    <div className="min-w-0 space-y-1">
                      <p className="font-medium">
                        {r.editable ? (
                          <Link
                            href={`/admin/resources/${r.id}`}
                            className="underline-offset-4 hover:underline"
                          >
                            {r.title}
                          </Link>
                        ) : (
                          r.title
                        )}
                      </p>
                      <p className="text-sm text-muted-foreground">{r.summary}</p>
                      <p className="flex flex-wrap gap-2 text-xs">
                        <Badge variant="outline">{titleCase(r.resource_type)}</Badge>
                        <Badge variant={r.is_published ? "success" : "info"}>
                          {r.is_published ? "Published" : "Draft"}
                        </Badge>
                        <Badge variant="outline">
                          {r.audience === "faculty" ? "For staff" : "For students"}
                        </Badge>
                        {!r.editable && <Badge variant="secondary">Shipped with MindMitra</Badge>}
                        {r.reviewed_at && (
                          <span className="text-muted-foreground">
                            Reviewed {formatShortDate(r.reviewed_at)}
                          </span>
                        )}
                      </p>
                    </div>
                    {r.editable ? (
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            void act(r.is_published ? "Withdrawn" : "Published", () =>
                              api.setPublished(r.id, !r.is_published),
                            )
                          }
                        >
                          {r.is_published ? "Withdraw" : "Publish"}
                          <span className="sr-only"> {r.title}</span>
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => void remove(r)}>
                          Delete<span className="sr-only"> {r.title}</span>
                        </Button>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">Read only</p>
                    )}
                  </li>
                ))}
              </ul>
            </SectionCard>
          )
        }
      </DataView>
    </>
  );
}

function ResourceForm({ resource }: { resource: AdminResource | null }) {
  const api = useAdminApi();
  const router = useRouter();
  const [v, setV] = React.useState({
    title: resource?.title ?? "",
    summary: resource?.summary ?? "",
    resource_type: resource?.resource_type ?? "article",
    body: resource?.body ?? "",
    url: resource?.url ?? "",
    tags: (resource?.tags ?? []).join(", "),
    language: resource?.language ?? "en",
    duration: resource?.duration_minutes ? String(resource.duration_minutes) : "",
  });
  const [publish, setPublish] = React.useState(false);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();
  const set =
    (k: keyof typeof v) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
      setV({ ...v, [k]: e.target.value });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!v.title.trim()) found.title = "Enter a title.";
    if (!v.summary.trim()) found.summary = "Add a short summary.";
    if (!v.body.trim() && !v.url.trim()) found.body = "Add some text or a link.";
    if (v.url.trim() && !v.url.trim().startsWith("https://"))
      found.url = "Links must start with https://";
    if (v.duration && !(Number(v.duration) >= 1 && Number(v.duration) <= 600))
      found.duration = "Use a number of minutes from 1 to 600.";
    if (splitList(v.tags).length > 10) found.tags = "Use at most 10 tags.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const input: ResourceInput = {
      title: v.title.trim(),
      summary: v.summary.trim(),
      resource_type: v.resource_type,
      body: v.body.trim() || null,
      url: v.url.trim() || null,
      tags: splitList(v.tags),
      language: v.language.trim() || "en",
      duration_minutes: v.duration ? Number(v.duration) : null,
    };
    void run(async () => {
      if (resource) await api.updateResource(resource.id, input);
      else await api.createResource({ ...input, publish });
      notify.success(resource ? "Resource saved" : "Resource added");
      router.push("/admin/resources");
    }, "We couldn't save that resource.");
  }

  return (
    <form onSubmit={submit} noValidate className="max-w-2xl space-y-5">
      <Field label="Title" error={errors.title}>
        {(p) => <Input {...p} maxLength={200} value={v.title} onChange={set("title")} />}
      </Field>
      <Field
        label="Short summary"
        hint="One or two sentences shown in the list."
        error={errors.summary}
      >
        {(p) => (
          <Textarea {...p} rows={2} maxLength={500} value={v.summary} onChange={set("summary")} />
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Type">
          {(p) => (
            <NativeSelect {...p} value={v.resource_type} onChange={set("resource_type")}>
              {RESOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {titleCase(t)}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field label="Language code" hint="For example en or hi">
          {(p) => <Input {...p} maxLength={12} value={v.language} onChange={set("language")} />}
        </Field>
        <Field label="Minutes (optional)" error={errors.duration}>
          {(p) => (
            <Input
              {...p}
              type="number"
              min={1}
              max={600}
              value={v.duration}
              onChange={set("duration")}
            />
          )}
        </Field>
      </div>
      <Field
        label="Text"
        hint="Plain text. Leave empty if you are linking elsewhere."
        error={errors.body}
      >
        {(p) => (
          <Textarea {...p} rows={8} maxLength={20000} value={v.body} onChange={set("body")} />
        )}
      </Field>
      <Field label="Link (optional)" hint="Must be a secure https:// address." error={errors.url}>
        {(p) => <Input {...p} type="url" maxLength={500} value={v.url} onChange={set("url")} />}
      </Field>
      <Field
        label="Tags"
        hint="Separated by commas. Add “faculty” to keep it in the staff library, out of the student one."
        error={errors.tags}
      >
        {(p) => <Input {...p} value={v.tags} onChange={set("tags")} />}
      </Field>
      {!resource && (
        <div className="flex items-start gap-3">
          <Checkbox
            id="publish-now"
            checked={publish}
            onCheckedChange={(c) => setPublish(c === true)}
            className="mt-0.5"
          />
          <div className="grid gap-1">
            <Label htmlFor="publish-now" className="font-normal">
              Publish straight away
            </Label>
            <p className="text-sm text-muted-foreground">
              Publishing records that you reviewed it. Leave unticked to save a draft.
            </p>
          </div>
        </div>
      )}
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <div className="flex gap-2">
        <SaveButton pending={pending}>{resource ? "Save changes" : "Add resource"}</SaveButton>
        <Button asChild variant="ghost">
          <Link href="/admin/resources">Cancel</Link>
        </Button>
      </div>
    </form>
  );
}

export function NewResourceView() {
  return (
    <>
      <PageHeader title="New resource" description="Write it for the people who will read it." />
      <ResourceForm resource={null} />
    </>
  );
}

export function EditResourceView({ id }: { id: string }) {
  const api = useAdminApi();
  const resource = useQuery(`admin-resource-${id}`, () => api.resource(id));
  return (
    <DataView query={resource}>
      {(r) => (
        <>
          <PageHeader
            title="Edit resource"
            description={
              r.is_published
                ? "This is published. Saving counts as a new review by you."
                : "This is a draft. Publish it from the list when it is ready."
            }
          />
          {r.editable ? (
            <ResourceForm resource={r} />
          ) : (
            <InlineAlert tone="info">
              This resource ships with MindMitra and can&apos;t be changed here.
            </InlineAlert>
          )}
        </>
      )}
    </DataView>
  );
}
