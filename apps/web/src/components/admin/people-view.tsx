"use client";

import { MoreHorizontal, UserPlus, Users } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { useModal } from "@/components/providers/modal-provider";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { NativeSelect } from "@/components/student/form-bits";
import { SegmentedTabs } from "@/components/therapist/shared";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import type {
  AdminStudent,
  AdminTeacher,
  AdminTherapist,
  Department,
} from "@/lib/api/admin-schemas";
import { describeError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { formatShortDate, titleCase } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";
import { notify } from "@/lib/toast";

import { InviteForm, StudentForm, TeacherForm, TherapistForm } from "./people-forms";
import { FormDialog, Pager, SearchBox, Table, UserStatusBadge, useDebounced } from "./shared";

type Tab = "student" | "teacher" | "therapist" | "administrator" | "all";
const PAGE = 25;

interface Row {
  id: string;
  name: string;
  email: string;
  status: string;
  role: string;
  detail: string;
  edit?: () => void;
}

type Editing =
  | { kind: "student"; row: AdminStudent }
  | { kind: "teacher"; row: AdminTeacher }
  | { kind: "therapist"; row: AdminTherapist };

export function PeopleView() {
  const api = useAdminApi();
  const { user } = useAuth();
  const modal = useModal();
  const [tab, setTab] = React.useState<Tab>("student");
  const [search, setSearch] = React.useState("");
  const [status, setStatus] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const q = useDebounced(search.trim());
  const [inviting, setInviting] = React.useState(false);
  const [editing, setEditing] = React.useState<Editing | null>(null);
  const departments = useQuery("admin-departments-list", () => api.departments());

  const data = useQuery(`admin-people-${tab}-${q}-${status}-${offset}`, async () => {
    const query = { q: q || undefined, status: status || undefined, limit: PAGE, offset };
    if (tab === "student") {
      const page = await api.students(query);
      return {
        total: page.total,
        rows: page.items.map((s): Row => ({
          id: s.id,
          name: s.full_name,
          email: s.email,
          status: s.status,
          role: "student",
          detail: `${s.department_name} · year ${s.year_of_study} · ${s.student_number}`,
          edit: () => setEditing({ kind: "student", row: s }),
        })),
      };
    }
    if (tab === "teacher") {
      const page = await api.teachers(query);
      return {
        total: page.total,
        rows: page.items.map((t): Row => ({
          id: t.id,
          name: t.full_name,
          email: t.email,
          status: t.status,
          role: "teacher",
          detail: `${t.department_name} · ${t.courses} course${t.courses === 1 ? "" : "s"}`,
          edit: () => setEditing({ kind: "teacher", row: t }),
        })),
      };
    }
    if (tab === "therapist") {
      const page = await api.therapists(query);
      return {
        total: page.total,
        rows: page.items.map((t): Row => ({
          id: t.id,
          name: t.full_name,
          email: t.email,
          status: t.status,
          role: "therapist",
          detail: `${titleCase(t.verification_status)} · ${t.caseload} of ${t.max_caseload} students`,
          edit: () => setEditing({ kind: "therapist", row: t }),
        })),
      };
    }
    const page = await api.users({ ...query, role: tab === "all" ? undefined : tab });
    return {
      total: page.total,
      rows: page.items.map((u): Row => ({
        id: u.id,
        name: u.full_name,
        email: u.email,
        status: u.status,
        role: u.role,
        detail: u.last_login_at
          ? `Last signed in ${formatShortDate(u.last_login_at)}`
          : "Has not signed in",
      })),
    };
  });

  function changeTab(next: Tab) {
    setTab(next);
    setOffset(0);
  }

  async function act(label: string, run: () => Promise<unknown>) {
    try {
      await run();
      notify.success(label);
      void data.reload();
    } catch (e) {
      notify.error("That didn't work", describeError(e));
    }
  }

  async function setUserStatus(row: Row, next: "active" | "suspended" | "deactivated") {
    if (next !== "active") {
      const ok = await modal.confirm({
        title: next === "suspended" ? `Suspend ${row.name}?` : `Deactivate ${row.name}?`,
        description:
          "They will be signed out everywhere and cannot sign in. " +
          (next === "suspended" ? "You can reactivate them later." : "Use this when they leave."),
        confirmLabel: next === "suspended" ? "Suspend" : "Deactivate",
        destructive: true,
      });
      if (!ok) return;
    }
    await act(`${row.name} is now ${next}`, () => api.setUserStatus(row.id, next));
  }

  return (
    <>
      <PageHeader
        title="People"
        description="Invite, update and suspend accounts. You manage accounts, not what people write."
        actions={
          <Button onClick={() => setInviting(true)}>
            <UserPlus aria-hidden="true" />
            Invite someone
          </Button>
        }
      />
      <SegmentedTabs
        label="Role"
        value={tab}
        onChange={changeTab}
        options={[
          { value: "student", label: "Students" },
          { value: "teacher", label: "Teachers" },
          { value: "therapist", label: "Therapists" },
          { value: "administrator", label: "Administrators" },
          { value: "all", label: "Everyone" },
        ]}
      />
      <div className="flex flex-wrap items-end gap-3">
        <SearchBox
          label="Search by name or email"
          value={search}
          onChange={(v) => {
            setSearch(v);
            setOffset(0);
          }}
        />
        <div className="space-y-1">
          <Label htmlFor="people-status" className="sr-only">
            Status
          </Label>
          <NativeSelect
            id="people-status"
            className="w-44"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Any status</option>
            <option value="active">Active</option>
            <option value="invited">Invited</option>
            <option value="suspended">Suspended</option>
            <option value="deactivated">Deactivated</option>
          </NativeSelect>
        </div>
      </div>
      <DataView query={data}>
        {({ rows, total }) =>
          rows.length === 0 ? (
            <EmptyState
              icon={Users}
              title="No one matches"
              description="Try a different search, or invite someone."
            />
          ) : (
            <SectionCard title={`${total} ${total === 1 ? "person" : "people"}`}>
              <Table
                caption="People in your institution"
                head={["Name", "Role", "Status", "Details", "Actions"]}
                minWidth="48rem"
              >
                {rows.map((r) => {
                  const self = r.id === user?.id;
                  return (
                    <tr key={r.id}>
                      <th scope="row" className="py-3 pr-4 font-normal">
                        <span className="block font-medium">{r.name}</span>
                        <span className="block break-all text-muted-foreground">{r.email}</span>
                      </th>
                      <td className="py-3 pr-4">{titleCase(r.role)}</td>
                      <td className="py-3 pr-4">
                        <UserStatusBadge status={r.status} />
                      </td>
                      <td className="py-3 pr-4 text-muted-foreground">{r.detail}</td>
                      <td className="py-3">
                        {self ? (
                          <span className="text-muted-foreground">This is you</span>
                        ) : (
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Actions for ${r.name}`}
                              >
                                <MoreHorizontal aria-hidden="true" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              {r.edit && (
                                <DropdownMenuItem onSelect={r.edit}>Edit details</DropdownMenuItem>
                              )}
                              {r.status === "invited" && (
                                <DropdownMenuItem
                                  onSelect={() =>
                                    void act("Invitation sent again", () => api.resendInvite(r.id))
                                  }
                                >
                                  Send the invitation again
                                </DropdownMenuItem>
                              )}
                              {r.status === "active" && (
                                <DropdownMenuItem
                                  onSelect={() =>
                                    void act(`${r.name} was signed out everywhere`, () =>
                                      api.signOutEverywhere(r.id),
                                    )
                                  }
                                >
                                  Sign out everywhere
                                </DropdownMenuItem>
                              )}
                              <DropdownMenuSeparator />
                              {(r.status === "suspended" || r.status === "deactivated") && (
                                <DropdownMenuItem onSelect={() => void setUserStatus(r, "active")}>
                                  Reactivate
                                </DropdownMenuItem>
                              )}
                              {r.status === "active" && (
                                <DropdownMenuItem
                                  onSelect={() => void setUserStatus(r, "suspended")}
                                >
                                  Suspend
                                </DropdownMenuItem>
                              )}
                              {r.status !== "deactivated" && (
                                <DropdownMenuItem
                                  onSelect={() => void setUserStatus(r, "deactivated")}
                                >
                                  Deactivate
                                </DropdownMenuItem>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </Table>
              <Pager offset={offset} limit={PAGE} total={total} onChange={setOffset} />
            </SectionCard>
          )
        }
      </DataView>

      <FormDialog
        open={inviting}
        onClose={() => setInviting(false)}
        title="Invite someone"
        description="They get an email with a link to choose their own password."
      >
        <DataView query={departments} skeleton={null}>
          {(list) => (
            <InviteForm
              departments={list}
              initialRole={tab === "all" ? "student" : tab}
              onCancel={() => setInviting(false)}
              onDone={() => {
                setInviting(false);
                void data.reload();
              }}
            />
          )}
        </DataView>
      </FormDialog>

      <FormDialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing ? `Edit ${editing.row.full_name}` : "Edit"}
      >
        {editing && (
          <DataView query={departments} skeleton={null}>
            {(list: Department[]) => {
              const done = () => {
                setEditing(null);
                void data.reload();
              };
              const cancel = () => setEditing(null);
              if (editing.kind === "student")
                return (
                  <StudentForm
                    student={editing.row}
                    departments={list}
                    onDone={done}
                    onCancel={cancel}
                  />
                );
              if (editing.kind === "teacher")
                return (
                  <TeacherForm
                    teacher={editing.row}
                    departments={list}
                    onDone={done}
                    onCancel={cancel}
                  />
                );
              return <TherapistForm therapist={editing.row} onDone={done} onCancel={cancel} />;
            }}
          </DataView>
        )}
      </FormDialog>
    </>
  );
}
