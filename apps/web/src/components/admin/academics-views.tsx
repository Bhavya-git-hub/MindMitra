"use client";

import { GraduationCap, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { useModal } from "@/components/providers/modal-provider";
import { EmptyState } from "@/components/states/empty-state";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, useSubmit } from "@/components/student/form-bits";
import { SegmentedTabs } from "@/components/therapist/shared";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Course, Department } from "@/lib/api/admin-schemas";
import { describeError } from "@/lib/api/errors";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";
import { notify } from "@/lib/toast";

import { Field, FormActions, FormDialog, SearchBox, Table, useDebounced } from "./shared";

function DepartmentForm({
  department,
  onDone,
  onCancel,
}: {
  department: Department | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [name, setName] = React.useState(department?.name ?? "");
  const [code, setCode] = React.useState(department?.code ?? "");
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = "Enter a name.";
    if (!/^[A-Za-z0-9][A-Za-z0-9-]{0,19}$/.test(code.trim()))
      found.code = "Use up to 20 letters, digits or hyphens.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      if (department) await api.updateDepartment(department.id, { name, code });
      else await api.createDepartment({ name, code });
      notify.success(department ? "Department saved" : "Department added");
      onDone();
    }, "We couldn't save that department.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field label="Name" error={errors.name}>
        {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
      </Field>
      <Field
        label="Short code"
        hint="Used when inviting people, for example CS."
        error={errors.code}
      >
        {(p) => <Input {...p} value={code} onChange={(e) => setCode(e.target.value)} />}
      </Field>
      <FormActions pending={pending} error={error} onCancel={onCancel} />
    </form>
  );
}

function CourseForm({
  departments,
  onDone,
  onCancel,
}: {
  departments: Department[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [v, setV] = React.useState({
    department_id: "",
    code: "",
    title: "",
    term: `${new Date().getFullYear()}-autumn`,
    credits: "3",
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setV({ ...v, [k]: e.target.value });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!v.department_id) found.department_id = "Choose a department.";
    if (!v.code.trim()) found.code = "Enter a course code.";
    if (!v.title.trim()) found.title = "Enter a title.";
    if (!/^\d{4}-[a-z]{3,10}$/.test(v.term.trim().toLowerCase()))
      found.term = "Use a term like 2026-autumn.";
    const credits = Number(v.credits);
    if (!Number.isInteger(credits) || credits < 0 || credits > 30)
      found.credits = "Use a whole number from 0 to 30.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      await api.createCourse({ ...v, credits });
      notify.success("Course added");
      onDone();
    }, "We couldn't add that course.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field label="Department" error={errors.department_id}>
        {(p) => (
          <NativeSelect {...p} value={v.department_id} onChange={set("department_id")}>
            <option value="">Choose…</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </NativeSelect>
        )}
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Course code" error={errors.code}>
          {(p) => <Input {...p} value={v.code} onChange={set("code")} />}
        </Field>
        <Field label="Term" hint="For example 2026-autumn" error={errors.term}>
          {(p) => <Input {...p} value={v.term} onChange={set("term")} />}
        </Field>
      </div>
      <Field label="Title" error={errors.title}>
        {(p) => <Input {...p} value={v.title} onChange={set("title")} />}
      </Field>
      <Field label="Credits" error={errors.credits}>
        {(p) => (
          <Input
            {...p}
            type="number"
            min={0}
            max={30}
            value={v.credits}
            onChange={set("credits")}
          />
        )}
      </Field>
      <FormActions pending={pending} error={error} onCancel={onCancel} submit="Add course" />
    </form>
  );
}

function DepartmentsTab() {
  const api = useAdminApi();
  const modal = useModal();
  const list = useQuery("admin-departments", () => api.departments());
  const [editing, setEditing] = React.useState<Department | "new" | null>(null);

  async function remove(d: Department) {
    const ok = await modal.confirm({
      title: `Delete ${d.name}?`,
      description: "Only an empty department can be deleted.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.deleteDepartment(d.id);
      notify.success("Department deleted");
      void list.reload();
    } catch (e) {
      notify.error("That department can't be deleted", describeError(e));
    }
  }

  return (
    <>
      <div className="flex justify-end">
        <Button onClick={() => setEditing("new")}>
          <Plus aria-hidden="true" />
          Add department
        </Button>
      </div>
      <DataView query={list}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState
              icon={GraduationCap}
              title="No departments yet"
              description="Add one so you can invite students and teachers."
            />
          ) : (
            <SectionCard title={`${rows.length} department${rows.length === 1 ? "" : "s"}`}>
              <Table
                caption="Departments"
                head={["Department", "Code", "Students", "Teachers", "Courses", "Actions"]}
                minWidth="44rem"
              >
                {rows.map((d) => (
                  <tr key={d.id}>
                    <th scope="row" className="py-3 pr-4 font-medium">
                      {d.name}
                    </th>
                    <td className="py-3 pr-4">{d.code}</td>
                    <td className="py-3 pr-4">{d.students}</td>
                    <td className="py-3 pr-4">{d.teachers}</td>
                    <td className="py-3 pr-4">{d.courses}</td>
                    <td className="space-x-2 py-3">
                      <Button size="sm" variant="outline" onClick={() => setEditing(d)}>
                        Edit<span className="sr-only"> {d.name}</span>
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void remove(d)}>
                        Delete<span className="sr-only"> {d.name}</span>
                      </Button>
                    </td>
                  </tr>
                ))}
              </Table>
            </SectionCard>
          )
        }
      </DataView>
      <FormDialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Add a department" : "Edit department"}
      >
        {editing && (
          <DepartmentForm
            department={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onDone={() => {
              setEditing(null);
              void list.reload();
            }}
          />
        )}
      </FormDialog>
    </>
  );
}

function CoursesTab() {
  const api = useAdminApi();
  const [search, setSearch] = React.useState("");
  const [department, setDepartment] = React.useState("");
  const q = useDebounced(search.trim());
  const departments = useQuery("admin-departments-list", () => api.departments());
  const courses = useQuery(`admin-courses-${q}-${department}`, () =>
    api.courses({ q: q || undefined, department_id: department || undefined }),
  );
  const [adding, setAdding] = React.useState(false);

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <SearchBox label="Search courses" value={search} onChange={setSearch} />
          <DataView query={departments} skeleton={null}>
            {(list) => (
              <NativeSelect
                aria-label="Department"
                className="w-56"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              >
                <option value="">All departments</option>
                {list.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </NativeSelect>
            )}
          </DataView>
        </div>
        <Button onClick={() => setAdding(true)}>
          <Plus aria-hidden="true" />
          Add course
        </Button>
      </div>
      <DataView query={courses}>
        {(rows: Course[]) =>
          rows.length === 0 ? (
            <EmptyState icon={GraduationCap} title="No courses match" />
          ) : (
            <SectionCard title={`${rows.length} course${rows.length === 1 ? "" : "s"}`}>
              <Table
                caption="Courses"
                head={["Course", "Department", "Term", "Teachers", "Enrolled"]}
                minWidth="40rem"
              >
                {rows.map((c) => (
                  <tr key={c.id}>
                    <th scope="row" className="py-3 pr-4 font-normal">
                      <Link
                        href={`/admin/academics/courses/${c.id}`}
                        className="font-medium underline-offset-4 hover:underline"
                      >
                        {c.code} {c.title}
                      </Link>
                    </th>
                    <td className="py-3 pr-4">{c.department_name}</td>
                    <td className="py-3 pr-4">{c.term}</td>
                    <td className="py-3 pr-4">{c.teachers}</td>
                    <td className="py-3 pr-4">{c.enrolled}</td>
                  </tr>
                ))}
              </Table>
            </SectionCard>
          )
        }
      </DataView>
      <FormDialog open={adding} onClose={() => setAdding(false)} title="Add a course">
        <DataView query={departments} skeleton={null}>
          {(list) => (
            <CourseForm
              departments={list}
              onCancel={() => setAdding(false)}
              onDone={() => {
                setAdding(false);
                void courses.reload();
              }}
            />
          )}
        </DataView>
      </FormDialog>
    </>
  );
}

export function AcademicsView() {
  const [tab, setTab] = React.useState<"departments" | "courses">("departments");
  return (
    <>
      <PageHeader
        title="Departments and courses"
        description="The academic structure. Teachers see anonymous figures for their department and classes, so who belongs where matters."
      />
      <SegmentedTabs
        label="Show"
        value={tab}
        onChange={setTab}
        options={[
          { value: "departments", label: "Departments" },
          { value: "courses", label: "Courses" },
        ]}
      />
      {tab === "departments" ? <DepartmentsTab /> : <CoursesTab />}
    </>
  );
}

function AddPerson({
  label,
  options,
  onAdd,
}: {
  label: string;
  options: { id: string; label: string }[];
  onAdd: (id: string) => Promise<void>;
}) {
  const [chosen, setChosen] = React.useState("");
  const { pending, run } = useSubmit();
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!chosen) return;
        void run(async () => {
          await onAdd(chosen);
          setChosen("");
        });
      }}
    >
      <NativeSelect
        aria-label={label}
        className="w-64"
        value={chosen}
        onChange={(e) => setChosen(e.target.value)}
      >
        <option value="">{label}…</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </NativeSelect>
      <Button type="submit" size="sm" disabled={!chosen || pending}>
        Add
      </Button>
    </form>
  );
}

export function CourseDetailView({ id }: { id: string }) {
  const api = useAdminApi();
  const router = useRouter();
  const modal = useModal();
  const detail = useQuery(`admin-course-${id}`, () => api.course(id));
  const teachers = useQuery(
    "admin-all-teachers",
    async () => (await api.teachers({ limit: 200 })).items,
  );
  const [student, setStudent] = React.useState("");
  const q = useDebounced(student.trim());
  const found = useQuery(`admin-student-search-${q}`, async () =>
    q.length < 2 ? [] : (await api.students({ q, limit: 10 })).items,
  );
  const [editing, setEditing] = React.useState(false);

  async function act(label: string, run: () => Promise<unknown>) {
    try {
      await run();
      notify.success(label);
      void detail.reload();
    } catch (e) {
      notify.error("That didn't work", describeError(e));
    }
  }

  async function removeCourse(title: string) {
    const ok = await modal.confirm({
      title: `Delete ${title}?`,
      description: "Only a course with no enrolment history can be deleted.",
      confirmLabel: "Delete",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.deleteCourse(id);
      notify.success("Course deleted");
      router.push("/admin/academics");
    } catch (e) {
      notify.error("That course can't be deleted", describeError(e));
    }
  }

  return (
    <DataView query={detail}>
      {(d) => (
        <>
          <PageHeader
            title={`${d.course.code} ${d.course.title}`}
            description={`${d.course.department_name} · ${d.course.term} · ${d.course.credits} credits`}
            actions={
              <>
                <Button asChild variant="ghost">
                  <Link href="/admin/academics">Back to courses</Link>
                </Button>
                <Button variant="outline" onClick={() => setEditing(true)}>
                  Edit
                </Button>
                <Button variant="outline" onClick={() => void removeCourse(d.course.title)}>
                  Delete
                </Button>
              </>
            }
          />
          <SectionCard
            title="Teachers"
            description="Teachers see anonymous figures for the classes they teach."
          >
            <ul className="divide-y">
              {d.teachers.length === 0 && (
                <li className="py-3 text-sm text-muted-foreground">No teacher assigned yet.</li>
              )}
              {d.teachers.map((t) => (
                <li key={t.id} className="flex items-center justify-between gap-3 py-3">
                  <span>
                    {t.full_name} <span className="text-muted-foreground">· {t.number}</span>
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void act("Teacher removed", () => api.unassignTeacher(id, t.id))}
                  >
                    Remove<span className="sr-only"> {t.full_name}</span>
                  </Button>
                </li>
              ))}
            </ul>
            <div className="pt-4">
              <DataView query={teachers} skeleton={null}>
                {(all) => (
                  <AddPerson
                    label="Add a teacher"
                    options={all
                      .filter((t) => !d.teachers.some((x) => x.id === t.id))
                      .map((t) => ({ id: t.id, label: `${t.full_name} (${t.department_name})` }))}
                    onAdd={async (tid) => {
                      await act("Teacher added", () => api.assignTeacher(id, tid));
                    }}
                  />
                )}
              </DataView>
            </div>
          </SectionCard>
          <SectionCard
            title={`Enrolled students (${d.course.enrolled})`}
            description="Changing who is enrolled changes the class's anonymous figures straight away."
          >
            <ul className="divide-y">
              {d.students.length === 0 && (
                <li className="py-3 text-sm text-muted-foreground">No students enrolled.</li>
              )}
              {d.students.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-3 py-3">
                  <span>
                    {s.full_name} <span className="text-muted-foreground">· {s.number}</span>
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void act("Student removed", () => api.drop(id, s.id))}
                  >
                    Remove<span className="sr-only"> {s.full_name}</span>
                  </Button>
                </li>
              ))}
            </ul>
            <div className="space-y-2 pt-4">
              <Field
                label="Find a student to enrol"
                hint="Type at least two letters of a name or number."
              >
                {(p) => (
                  <Input
                    {...p}
                    type="search"
                    className="max-w-sm"
                    value={student}
                    onChange={(e) => setStudent(e.target.value)}
                  />
                )}
              </Field>
              <DataView query={found} skeleton={null}>
                {(list) => (
                  <ul className="divide-y">
                    {list
                      .filter((s) => !d.students.some((x) => x.id === s.id))
                      .map((s) => (
                        <li key={s.id} className="flex items-center justify-between gap-3 py-2">
                          <span>
                            {s.full_name}{" "}
                            <span className="text-muted-foreground">
                              · {s.student_number} · {s.department_name}
                            </span>
                          </span>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void act("Student enrolled", () => api.enrol(id, s.id))}
                          >
                            Enrol<span className="sr-only"> {s.full_name}</span>
                          </Button>
                        </li>
                      ))}
                  </ul>
                )}
              </DataView>
            </div>
          </SectionCard>
          <FormDialog open={editing} onClose={() => setEditing(false)} title="Edit course">
            <CourseEditForm
              course={d.course}
              onCancel={() => setEditing(false)}
              onDone={() => {
                setEditing(false);
                void detail.reload();
              }}
            />
          </FormDialog>
        </>
      )}
    </DataView>
  );
}

function CourseEditForm({
  course,
  onDone,
  onCancel,
}: {
  course: Course;
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [title, setTitle] = React.useState(course.title);
  const [credits, setCredits] = React.useState(String(course.credits));
  const { pending, error, run } = useSubmit();
  return (
    <form
      noValidate
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        void run(async () => {
          await api.updateCourse(course.id, { title, credits: Number(credits) });
          notify.success("Course saved");
          onDone();
        }, "We couldn't save that course.");
      }}
    >
      <Field label="Title">
        {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} />}
      </Field>
      <Field label="Credits">
        {(p) => (
          <Input
            {...p}
            type="number"
            min={0}
            max={30}
            value={credits}
            onChange={(e) => setCredits(e.target.value)}
          />
        )}
      </Field>
      <FormActions pending={pending} error={error} onCancel={onCancel} />
    </form>
  );
}
