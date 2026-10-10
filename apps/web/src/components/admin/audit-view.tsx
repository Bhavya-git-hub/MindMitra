"use client";

import { Download, ShieldCheck, ShieldX } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/states/empty-state";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect } from "@/components/student/form-bits";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { AuditEvent } from "@/lib/api/admin-schemas";
import { describeError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";

import { Table } from "./shared";

const PAGE = 50;

interface Filters {
  action: string;
  outcome: string;
  since: string;
  until: string;
}

const NONE: Filters = { action: "", outcome: "", since: "", until: "" };

/** A day picked in the page, as the start of that day and the start of the next, in UTC. */
const startOf = (day: string) => (day ? `${day}T00:00:00Z` : undefined);
const endOf = (day: string) =>
  day ? new Date(new Date(`${day}T00:00:00Z`).getTime() + 86_400_000).toISOString() : undefined;

function apiFilter(f: Filters) {
  return {
    action: f.action || undefined,
    outcome: f.outcome || undefined,
    since: startOf(f.since),
    until: endOf(f.until),
  };
}

const details = (d: Record<string, unknown>) =>
  Object.entries(d)
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(", ");

const short = (id: string | null) => (id ? id.slice(0, 8) : "system");

export function AuditView() {
  const api = useAdminApi();
  const [draft, setDraft] = React.useState<Filters>(NONE);
  const [applied, setApplied] = React.useState<Filters>(NONE);
  const actions = useQuery("admin-audit-actions", () => api.auditActions());
  const first = useQuery(`admin-audit-${JSON.stringify(applied)}`, () =>
    api.audit({ ...apiFilter(applied), limit: PAGE }),
  );
  // Older pages belong to the filters they were loaded with; new filters start again.
  const key = JSON.stringify(applied);
  const [loaded, setLoaded] = React.useState<{ key: string; rows: AuditEvent[]; done: boolean }>({
    key,
    rows: [],
    done: false,
  });
  const older = loaded.key === key ? loaded.rows : [];
  const more = loaded.key === key ? !loaded.done : true;
  const [loadingMore, setLoadingMore] = React.useState(false);
  const [problem, setProblem] = React.useState<string>();
  const [chain, setChain] = React.useState<{
    intact: boolean;
    events: number;
    seq: number | null;
  }>();
  const [busy, setBusy] = React.useState(false);

  async function loadOlder(last: number) {
    setLoadingMore(true);
    setProblem(undefined);
    try {
      const rows = await api.audit({ ...apiFilter(applied), before_seq: last, limit: PAGE });
      setLoaded((prev) => ({
        key,
        rows: [...(prev.key === key ? prev.rows : []), ...rows],
        done: rows.length < PAGE,
      }));
    } catch (e) {
      setProblem(describeError(e));
    } finally {
      setLoadingMore(false);
    }
  }

  async function verify() {
    setBusy(true);
    setProblem(undefined);
    try {
      const r = await api.verifyAuditChain();
      setChain({ intact: r.intact, events: r.events, seq: r.first_bad_seq });
    } catch (e) {
      setProblem(describeError(e));
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setProblem(undefined);
    try {
      const csv = await api.auditCsv(apiFilter(applied));
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "audit-log.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setProblem(describeError(e, "We couldn't prepare the download."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who did what, and when. The log records actions, never the words people wrote. Looking at it is recorded too."
        actions={
          <>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void verify()}>
              <ShieldCheck aria-hidden="true" />
              Check the log is intact
            </Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void download()}>
              <Download aria-hidden="true" />
              Download CSV
            </Button>
          </>
        }
      />
      {chain && (
        <InlineAlert
          tone={chain.intact ? "success" : "destructive"}
          title={chain.intact ? "The log is intact" : "The log has been altered"}
        >
          {chain.intact
            ? `All ${chain.events} entries link up as they were written.`
            : `Entry ${chain.seq} does not match what was written. Tell your security contact.`}
        </InlineAlert>
      )}
      {problem && <InlineAlert tone="destructive">{problem}</InlineAlert>}

      <form
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(draft);
        }}
      >
        <div className="space-y-1">
          <Label htmlFor="audit-action">Action</Label>
          <NativeSelect
            id="audit-action"
            value={draft.action}
            onChange={(e) => setDraft({ ...draft, action: e.target.value })}
          >
            <option value="">Any action</option>
            <DataView query={actions} skeleton={null}>
              {(list) => (
                <>
                  {[...new Set(list.map((a) => `${a.split(".")[0]}.`))].map((family) => (
                    <option key={family} value={family}>
                      All {family.slice(0, -1).replace(/_/g, " ")} actions
                    </option>
                  ))}
                  {list.map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </>
              )}
            </DataView>
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-outcome">Outcome</Label>
          <NativeSelect
            id="audit-outcome"
            value={draft.outcome}
            onChange={(e) => setDraft({ ...draft, outcome: e.target.value })}
          >
            <option value="">Any outcome</option>
            <option value="allowed">Allowed</option>
            <option value="denied">Refused</option>
            <option value="error">Error</option>
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-since">From</Label>
          <Input
            id="audit-since"
            type="date"
            value={draft.since}
            onChange={(e) => setDraft({ ...draft, since: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-until">To</Label>
          <Input
            id="audit-until"
            type="date"
            value={draft.until}
            onChange={(e) => setDraft({ ...draft, until: e.target.value })}
          />
        </div>
        <div className="flex gap-2">
          <Button type="submit">Apply</Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setDraft(NONE);
              setApplied(NONE);
            }}
          >
            Clear
          </Button>
        </div>
      </form>

      <DataView query={first}>
        {(firstPage) => {
          const rows = [...firstPage, ...older];
          if (rows.length === 0)
            return (
              <EmptyState
                icon={ShieldX}
                title="No entries match"
                description="Try widening the filters."
              />
            );
          const canMore = more && (older.length > 0 || firstPage.length === PAGE);
          return (
            <SectionCard title={`${rows.length} entries, newest first`}>
              <Table
                caption="Audit log entries"
                head={["When", "Who", "Action", "Outcome", "About"]}
                minWidth="50rem"
              >
                {rows.map((e) => (
                  <tr key={e.seq}>
                    <td className="py-2 pr-4 whitespace-nowrap">{formatDateTime(e.occurred_at)}</td>
                    <td className="py-2 pr-4">
                      {e.actor_role ? `${e.actor_role} ` : ""}
                      <span className="text-muted-foreground">{short(e.actor_id)}</span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs">{e.action}</td>
                    <td className="py-2 pr-4">
                      <Badge variant={e.outcome === "allowed" ? "success" : "warning"}>
                        {e.outcome === "denied" ? "Refused" : e.outcome}
                      </Badge>
                    </td>
                    <td className="py-2 text-muted-foreground">
                      {[e.resource_type, e.reason, details(e.details)].filter(Boolean).join(" · ")}
                    </td>
                  </tr>
                ))}
              </Table>
              {canMore && (
                <div className="pt-4">
                  <Button
                    variant="outline"
                    disabled={loadingMore}
                    onClick={() => void loadOlder(rows[rows.length - 1]!.seq)}
                  >
                    Show older entries
                  </Button>
                </div>
              )}
            </SectionCard>
          );
        }}
      </DataView>
    </>
  );
}
