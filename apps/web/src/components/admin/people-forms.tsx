"use client";

import * as React from "react";

import { NativeSelect, useSubmit } from "@/components/student/form-bits";
import { Input } from "@/components/ui/input";
import type { NewUserInput } from "@/lib/api/admin-api";
import type {
  AdminStudent,
  AdminTeacher,
  AdminTherapist,
  Department,
} from "@/lib/api/admin-schemas";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { notify } from "@/lib/toast";

import { Field, FormActions, ROLE_LABELS } from "./shared";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function DepartmentSelect({
  departments,
  ...props
}: { departments: Department[] } & React.ComponentProps<"select">) {
  return (
    <NativeSelect {...props}>
      <option value="">Choose…</option>
      {departments.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name} ({d.code})
        </option>
      ))}
    </NativeSelect>
  );
}

/** Invite someone: they get a link to set their own password. */
export function InviteForm({
  departments,
  initialRole,
  onDone,
  onCancel,
}: {
  departments: Department[];
  initialRole: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [role, setRole] = React.useState(initialRole);
  const [v, setV] = React.useState({
    full_name: "",
    email: "",
    department: "",
    student_number: "",
    enrollment_year: String(new Date().getFullYear()),
    year_of_study: "1",
    employee_number: "",
    licence_number: "",
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setV({ ...v, [k]: e.target.value });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!v.full_name.trim()) found.full_name = "Enter their full name.";
    if (!EMAIL.test(v.email.trim())) found.email = "Enter a valid email address.";
    const needsDept = role === "student" || role === "teacher";
    const dept = departments.find((d) => d.id === v.department);
    if (needsDept && !dept) found.department = "Choose a department.";
    if (role === "student" && !v.student_number.trim()) found.student_number = "Enter the number.";
    if (role === "teacher" && !v.employee_number.trim())
      found.employee_number = "Enter the number.";
    if (role === "therapist" && !v.licence_number.trim())
      found.licence_number = "Enter the licence number.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const input: NewUserInput = {
      email: v.email.trim(),
      full_name: v.full_name.trim(),
      role,
    };
    if (needsDept && dept) input.department_code = dept.code;
    if (role === "student") {
      input.student_number = v.student_number.trim();
      input.enrollment_year = Number(v.enrollment_year);
      input.year_of_study = Number(v.year_of_study);
    }
    if (role === "teacher") input.employee_number = v.employee_number.trim();
    if (role === "therapist") input.licence_number = v.licence_number.trim();
    void run(async () => {
      await api.createUser(input);
      notify.success("Invitation sent", "They will get a link to choose their own password.");
      onDone();
    }, "We couldn't send that invitation.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field label="Role">
        {(p) => (
          <NativeSelect {...p} value={role} onChange={(e) => setRole(e.target.value)}>
            {Object.entries(ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        )}
      </Field>
      <Field label="Full name" error={errors.full_name}>
        {(p) => <Input {...p} autoComplete="off" value={v.full_name} onChange={set("full_name")} />}
      </Field>
      <Field label="Email" error={errors.email}>
        {(p) => (
          <Input {...p} type="email" autoComplete="off" value={v.email} onChange={set("email")} />
        )}
      </Field>
      {(role === "student" || role === "teacher") && (
        <Field label="Department" error={errors.department}>
          {(p) => (
            <DepartmentSelect
              {...p}
              departments={departments}
              value={v.department}
              onChange={set("department")}
            />
          )}
        </Field>
      )}
      {role === "student" && (
        <>
          <Field label="Student number" error={errors.student_number}>
            {(p) => <Input {...p} value={v.student_number} onChange={set("student_number")} />}
          </Field>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Year they started">
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min={1990}
                  max={2100}
                  value={v.enrollment_year}
                  onChange={set("enrollment_year")}
                />
              )}
            </Field>
            <Field label="Year of study">
              {(p) => (
                <Input
                  {...p}
                  type="number"
                  min={1}
                  max={8}
                  value={v.year_of_study}
                  onChange={set("year_of_study")}
                />
              )}
            </Field>
          </div>
        </>
      )}
      {role === "teacher" && (
        <Field label="Employee number" error={errors.employee_number}>
          {(p) => <Input {...p} value={v.employee_number} onChange={set("employee_number")} />}
        </Field>
      )}
      {role === "therapist" && (
        <Field
          label="Licence number"
          hint="They cannot see students until you verify this."
          error={errors.licence_number}
        >
          {(p) => <Input {...p} value={v.licence_number} onChange={set("licence_number")} />}
        </Field>
      )}
      <FormActions pending={pending} error={error} onCancel={onCancel} submit="Send invitation" />
    </form>
  );
}

export function StudentForm({
  student,
  departments,
  onDone,
  onCancel,
}: {
  student: AdminStudent;
  departments: Department[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [department, setDepartment] = React.useState(student.department_id);
  const [year, setYear] = React.useState(String(student.year_of_study));
  const [started, setStarted] = React.useState(String(student.enrollment_year));
  const [number, setNumber] = React.useState(student.student_number);
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    void run(async () => {
      await api.updateStudent(student.id, {
        department_id: department,
        year_of_study: Number(year),
        enrollment_year: Number(started),
        student_number: number.trim(),
      });
      notify.success("Student details saved");
      onDone();
    }, "We couldn't save those details.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field
        label="Department"
        hint="Moving a student changes which department's anonymous figures they count towards."
      >
        {(p) => (
          <DepartmentSelect
            {...p}
            departments={departments}
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          />
        )}
      </Field>
      <Field label="Student number">
        {(p) => <Input {...p} value={number} onChange={(e) => setNumber(e.target.value)} />}
      </Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Year they started">
          {(p) => (
            <Input
              {...p}
              type="number"
              min={1990}
              max={2100}
              value={started}
              onChange={(e) => setStarted(e.target.value)}
            />
          )}
        </Field>
        <Field label="Year of study">
          {(p) => (
            <Input
              {...p}
              type="number"
              min={1}
              max={8}
              value={year}
              onChange={(e) => setYear(e.target.value)}
            />
          )}
        </Field>
      </div>
      <FormActions pending={pending} error={error} onCancel={onCancel} />
    </form>
  );
}

export function TeacherForm({
  teacher,
  departments,
  onDone,
  onCancel,
}: {
  teacher: AdminTeacher;
  departments: Department[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [department, setDepartment] = React.useState(teacher.department_id);
  const [title, setTitle] = React.useState(teacher.title ?? "");
  const [number, setNumber] = React.useState(teacher.employee_number);
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    void run(async () => {
      await api.updateTeacher(teacher.id, {
        department_id: department,
        title: title.trim(),
        employee_number: number.trim(),
      });
      notify.success("Teacher details saved");
      onDone();
    }, "We couldn't save those details.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field label="Department" hint="Teachers see anonymous figures for their own department.">
        {(p) => (
          <DepartmentSelect
            {...p}
            departments={departments}
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          />
        )}
      </Field>
      <Field label="Title (optional)">
        {(p) => (
          <Input {...p} maxLength={100} value={title} onChange={(e) => setTitle(e.target.value)} />
        )}
      </Field>
      <Field label="Employee number">
        {(p) => <Input {...p} value={number} onChange={(e) => setNumber(e.target.value)} />}
      </Field>
      <FormActions pending={pending} error={error} onCancel={onCancel} />
    </form>
  );
}

export function TherapistForm({
  therapist,
  onDone,
  onCancel,
}: {
  therapist: AdminTherapist;
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [caseload, setCaseload] = React.useState(String(therapist.max_caseload));
  const [licence, setLicence] = React.useState(therapist.licence_number);
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();
  const licenceChanged = licence.trim() !== therapist.licence_number;

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const n = Number(caseload);
    if (!Number.isInteger(n) || n < 1 || n > 500) {
      setErrors({ caseload: "Use a whole number from 1 to 500." });
      return;
    }
    setErrors({});
    void run(async () => {
      await api.updateTherapist(therapist.id, {
        max_caseload: n,
        ...(licenceChanged ? { licence_number: licence.trim() } : {}),
      });
      notify.success("Therapist details saved");
      onDone();
    }, "We couldn't save those details.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field
        label="Most students at once"
        hint="New students are not matched once this is reached."
        error={errors.caseload}
      >
        {(p) => (
          <Input
            {...p}
            type="number"
            min={1}
            max={500}
            value={caseload}
            onChange={(e) => setCaseload(e.target.value)}
          />
        )}
      </Field>
      <Field
        label="Licence number"
        hint={
          licenceChanged
            ? "A new licence number sends them back to the verification queue."
            : undefined
        }
      >
        {(p) => <Input {...p} value={licence} onChange={(e) => setLicence(e.target.value)} />}
      </Field>
      <FormActions pending={pending} error={error} onCancel={onCancel} />
    </form>
  );
}
