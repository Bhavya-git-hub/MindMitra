"use client";

import { Download, Printer } from "lucide-react";
import * as React from "react";

import { InlineAlert } from "@/components/states/inline-alert";
import { Button } from "@/components/ui/button";
import { describeError } from "@/lib/api/errors";
import type { GroupRef } from "@/lib/api/teacher-api";
import type { WindowWeeks } from "@/lib/api/teacher-schemas";
import { useTeacherApi } from "@/lib/hooks/use-teacher-api";

/**
 * The anonymous report: print the page (the browser's "save as PDF" works too) or download the
 * weekly figures as CSV. Both come from the same privacy-checked figures the page shows.
 */
export function ReportActions({ group, weeks }: { group: GroupRef; weeks: WindowWeeks }) {
  const api = useTeacherApi();
  const [error, setError] = React.useState<string>();
  const [busy, setBusy] = React.useState(false);

  async function download() {
    setBusy(true);
    setError(undefined);
    try {
      const csv = await api.reportCsv(group, weeks);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `anonymous-wellbeing-report-${weeks}-weeks.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(describeError(e, "We couldn't prepare the download."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 print:hidden">
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => window.print()}>
          <Printer aria-hidden="true" />
          Print report
        </Button>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={download}>
          <Download aria-hidden="true" />
          Download CSV
        </Button>
      </div>
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
    </div>
  );
}
