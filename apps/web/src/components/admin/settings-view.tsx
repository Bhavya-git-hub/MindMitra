"use client";

import { Plus, ShieldCheck } from "lucide-react";
import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { useModal } from "@/components/providers/modal-provider";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { NativeSelect, SaveButton, useSubmit } from "@/components/student/form-bits";
import { SegmentedTabs } from "@/components/therapist/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CONTACT_KINDS, type CrisisContact, type SafetySettings } from "@/lib/api/admin-schemas";
import { describeError } from "@/lib/api/errors";
import { titleCase } from "@/lib/format";
import { useAdminApi } from "@/lib/hooks/use-admin-api";
import { useQuery } from "@/lib/hooks/use-query";
import { notify } from "@/lib/toast";

import { Field, FormActions, FormDialog, splitList } from "./shared";

function FixedRules({ rules }: { rules: string[] }) {
  return (
    <div className="rounded-lg border bg-secondary/40 p-4">
      <p className="flex items-center gap-2 text-sm font-medium">
        <ShieldCheck className="size-4" aria-hidden="true" />
        Always on, and not something to switch off
      </p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        {rules.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

function Toggle({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <Checkbox
        id={id}
        checked={checked}
        onCheckedChange={(c) => onChange(c === true)}
        className="mt-0.5"
      />
      <div className="grid gap-1">
        <Label htmlFor={id} className="font-normal">
          {label}
        </Label>
        <p className="text-sm text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}

function InstitutionTab() {
  const api = useAdminApi();
  const data = useQuery("admin-institution", () => api.institution());
  return (
    <DataView query={data}>
      {(inst) => <InstitutionForm key={inst.id} inst={inst} onSaved={() => void data.reload()} />}
    </DataView>
  );
}

function InstitutionForm({
  inst,
  onSaved,
}: {
  inst: { name: string; slug: string; region: string; email_domains: string[] };
  onSaved: () => void;
}) {
  const api = useAdminApi();
  const [name, setName] = React.useState(inst.name);
  const [domains, setDomains] = React.useState(inst.email_domains.join(", "));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const list = splitList(domains).map((d) => d.toLowerCase());
    const found: Record<string, string> = {};
    if (!name.trim()) found.name = "Enter a name.";
    if (list.some((d) => !/^[a-z0-9.-]+\.[a-z]{2,}$/.test(d)))
      found.domains = "Use domain names like college.example, separated by commas.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      await api.updateInstitution({ name: name.trim(), email_domains: list });
      notify.success("Institution details saved");
      onSaved();
    }, "We couldn't save that.");
  }

  return (
    <SectionCard
      title="Institution"
      description="Students whose email ends with one of these domains can register themselves."
    >
      <form onSubmit={submit} noValidate className="max-w-xl space-y-4">
        <Field label="Name" error={errors.name}>
          {(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}
        </Field>
        <Field
          label="Email domains for student sign-up"
          hint="Leave empty to stop self-registration; you can still invite people."
          error={errors.domains}
        >
          {(p) => <Input {...p} value={domains} onChange={(e) => setDomains(e.target.value)} />}
        </Field>
        <p className="text-sm text-muted-foreground">
          Short name <span className="font-medium">{inst.slug}</span> · data region{" "}
          <span className="font-medium">{inst.region}</span> (these two can&apos;t be changed here)
        </p>
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <SaveButton pending={pending}>Save</SaveButton>
      </form>
    </SectionCard>
  );
}

function NotificationsTab() {
  const api = useAdminApi();
  const data = useQuery("admin-notification-settings", () => api.notificationSettings());
  return (
    <DataView query={data}>
      {(s) => <NotificationsForm key={JSON.stringify(s.values)} settings={s} />}
    </DataView>
  );
}

function NotificationsForm({
  settings,
}: {
  settings: {
    values: {
      reminders_enabled: boolean;
      appointment_reminder_hours: number[];
      recommendation_notifications: boolean;
      goal_reminders: boolean;
      email_enabled: boolean;
    };
    fixed_rules: string[];
  };
}) {
  const api = useAdminApi();
  const [v, setV] = React.useState(settings.values);
  const [hours, setHours] = React.useState(settings.values.appointment_reminder_hours.join(", "));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const list = splitList(hours).map(Number);
    const found: Record<string, string> = {};
    if (list.length > 3) found.hours = "Choose at most three reminders.";
    else if (list.some((h) => !Number.isInteger(h) || h < 1 || h > 168))
      found.hours = "Use whole numbers of hours from 1 to 168, for example 24, 2.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    void run(async () => {
      await api.updateNotificationSettings({ ...v, appointment_reminder_hours: list });
      notify.success("Notification settings saved");
    }, "We couldn't save those settings.");
  }

  return (
    <SectionCard
      title="Notifications"
      description="What people are reminded about. Notifications never contain what someone wrote."
    >
      <form onSubmit={submit} noValidate className="max-w-xl space-y-5">
        <Toggle
          id="n-rec"
          label="Tell students when their therapist shares a suggestion"
          hint="The suggestion itself is always in their Suggestions page."
          checked={v.recommendation_notifications}
          onChange={(c) => setV({ ...v, recommendation_notifications: c })}
        />
        <InlineAlert tone="info" title="How reminders and email are sent">
          Appointment reminders go to the student and the therapist at the hours below while the
          reminder service runs for your deployment. Goal reminders are saved now and used in a
          later release. Emails go out only once an email provider is set up for your deployment.
        </InlineAlert>
        <Toggle
          id="n-rem"
          label="Remind people about upcoming appointments"
          hint="Sent a set number of hours before."
          checked={v.reminders_enabled}
          onChange={(c) => setV({ ...v, reminders_enabled: c })}
        />
        <Field
          label="Hours before an appointment"
          hint="Up to three, for example 24, 2."
          error={errors.hours}
        >
          {(p) => (
            <Input
              {...p}
              inputMode="numeric"
              className="max-w-xs"
              value={hours}
              onChange={(e) => setHours(e.target.value)}
            />
          )}
        </Field>
        <Toggle
          id="n-goal"
          label="Gentle reminders about students' own goals"
          hint="Only for goals a student set for themselves."
          checked={v.goal_reminders}
          onChange={(c) => setV({ ...v, goal_reminders: c })}
        />
        <Toggle
          id="n-mail"
          label="Also send notifications by email"
          hint="Emails say only that there is something new to see, never what it is."
          checked={v.email_enabled}
          onChange={(c) => setV({ ...v, email_enabled: c })}
        />
        <FixedRules rules={settings.fixed_rules} />
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <SaveButton pending={pending}>Save</SaveButton>
      </form>
    </SectionCard>
  );
}

function ContactForm({
  contact,
  onDone,
  onCancel,
}: {
  contact: CrisisContact | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const api = useAdminApi();
  const [v, setV] = React.useState({
    label: contact?.label ?? "",
    kind: contact?.kind ?? "campus",
    phone: contact?.phone ?? "",
    url: contact?.url ?? "",
    description: contact?.description ?? "",
    hours: contact?.hours ?? "",
    active: contact?.is_active ?? true,
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();
  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setV({ ...v, [k]: e.target.value });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const found: Record<string, string> = {};
    if (!v.label.trim()) found.label = "Enter a name.";
    if (!v.phone.trim() && !v.url.trim() && !v.description.trim())
      found.phone = "Add a phone number, a link or a short description.";
    if (v.url.trim() && !v.url.trim().startsWith("https://"))
      found.url = "Links must start with https://";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const body = {
      label: v.label.trim(),
      phone: v.phone.trim() || null,
      url: v.url.trim() || null,
      description: v.description.trim() || null,
      hours: v.hours.trim() || null,
      is_active: v.active,
    };
    void run(async () => {
      if (contact) await api.updateContact(contact.id, body);
      else await api.createContact({ ...body, kind: v.kind });
      notify.success("Contact saved");
      onDone();
    }, "We couldn't save that contact.");
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <Field label="Name" error={errors.label}>
        {(p) => <Input {...p} value={v.label} onChange={set("label")} />}
      </Field>
      {!contact && (
        <Field label="Kind">
          {(p) => (
            <NativeSelect {...p} value={v.kind} onChange={set("kind")}>
              {CONTACT_KINDS.map((k) => (
                <option key={k} value={k}>
                  {titleCase(k)}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
      )}
      <Field label="Phone" error={errors.phone}>
        {(p) => <Input {...p} type="tel" value={v.phone} onChange={set("phone")} />}
      </Field>
      <Field label="Link" error={errors.url}>
        {(p) => <Input {...p} type="url" value={v.url} onChange={set("url")} />}
      </Field>
      <Field label="Short description">
        {(p) => (
          <Input {...p} maxLength={300} value={v.description} onChange={set("description")} />
        )}
      </Field>
      <Field label="Hours">
        {(p) => <Input {...p} maxLength={80} value={v.hours} onChange={set("hours")} />}
      </Field>
      <Toggle
        id="c-active"
        label="Show this to students"
        hint="Hidden contacts stay here so you can turn them back on."
        checked={v.active}
        onChange={(c) => setV({ ...v, active: c })}
      />
      <FormActions pending={pending} error={error} onCancel={onCancel} />
    </form>
  );
}

function SafetyTab() {
  const api = useAdminApi();
  const modal = useModal();
  const safety = useQuery("admin-safety-settings", () => api.safetySettings());
  const contacts = useQuery("admin-crisis-contacts", () => api.crisisContacts());
  const [editing, setEditing] = React.useState<CrisisContact | "new" | null>(null);

  async function remove(c: CrisisContact) {
    const ok = await modal.confirm({
      title: `Remove ${c.label}?`,
      description: "Students will no longer see it. You can add it again later.",
      confirmLabel: "Remove",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.deleteContact(c.id);
      notify.success("Contact removed");
      void contacts.reload();
    } catch (e) {
      notify.error("That contact can't be removed", describeError(e));
    }
  }

  return (
    <>
      <DataView query={safety}>
        {(s) => (
          <>
            <SafetyForm key={s.values.alert_ack_minutes} settings={s} />
            <CompanionForm
              key={`${s.values.companion_enabled}-${s.values.companion_daily_messages}`}
              values={s.values}
            />
          </>
        )}
      </DataView>
      <DataView query={contacts}>
        {(rows) => (
          <SectionCard
            title="Crisis contacts"
            description="What students see on the urgent support page. At least one emergency contact must stay active."
            action={
              <Button size="sm" onClick={() => setEditing("new")}>
                <Plus aria-hidden="true" />
                Add contact
              </Button>
            }
          >
            <ul className="divide-y">
              {rows.map((c) => (
                <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="font-medium">{c.label}</p>
                    <p className="text-sm text-muted-foreground">
                      {[c.phone, c.url, c.description, c.hours].filter(Boolean).join(" · ")}
                    </p>
                    <p className="mt-1 flex gap-2 text-xs">
                      <Badge variant="outline">{titleCase(c.kind)}</Badge>
                      <Badge variant={c.is_active ? "success" : "outline"}>
                        {c.is_active ? "Shown" : "Hidden"}
                      </Badge>
                      {!c.editable && <Badge variant="secondary">Shipped with MindMitra</Badge>}
                    </p>
                  </div>
                  {c.editable && (
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => setEditing(c)}>
                        Edit<span className="sr-only"> {c.label}</span>
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => void remove(c)}>
                        Remove<span className="sr-only"> {c.label}</span>
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </SectionCard>
        )}
      </DataView>
      <FormDialog
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? "Add a contact" : "Edit contact"}
      >
        {editing && (
          <ContactForm
            contact={editing === "new" ? null : editing}
            onCancel={() => setEditing(null)}
            onDone={() => {
              setEditing(null);
              void contacts.reload();
            }}
          />
        )}
      </FormDialog>
    </>
  );
}

/** The AI companion's switch and daily message allowance. Crisis handling can't be turned off. */
function CompanionForm({ values }: { values: SafetySettings["values"] }) {
  const api = useAdminApi();
  const [enabled, setEnabled] = React.useState(values.companion_enabled);
  const [daily, setDaily] = React.useState(String(values.companion_daily_messages));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const n = Number(daily);
    if (!Number.isInteger(n) || n < 10 || n > 500) {
      setErrors({ daily: "Use a whole number from 10 to 500." });
      return;
    }
    setErrors({});
    void run(async () => {
      await api.updateSafetySettings({ companion_enabled: enabled, companion_daily_messages: n });
      notify.success("Companion settings saved");
    }, "We couldn't save those settings.");
  }

  return (
    <SectionCard
      title="AI companion"
      description="An AI that helps students reflect on everyday pressures. It is not a therapist and never diagnoses. If a message suggests a student may not be safe, it shows crisis contacts and alerts your counselling team instead of replying, even when the companion is switched off."
    >
      <form onSubmit={submit} noValidate className="max-w-xl space-y-5">
        <Toggle
          id="companion-enabled"
          label="Let students use the companion"
          hint="Switching it off stops new replies straight away. Students can still read and delete their conversations."
          checked={enabled}
          onChange={setEnabled}
        />
        <Field
          label="Messages each student can send a day"
          hint="Keeps use sensible and costs predictable. Messages that suggest a crisis are never limited."
          error={errors.daily}
        >
          {(p) => (
            <Input
              {...p}
              type="number"
              min={10}
              max={500}
              className="max-w-xs"
              value={daily}
              onChange={(e) => setDaily(e.target.value)}
            />
          )}
        </Field>
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <SaveButton pending={pending}>Save companion settings</SaveButton>
      </form>
    </SectionCard>
  );
}

function SafetyForm({ settings }: { settings: SafetySettings }) {
  const api = useAdminApi();
  const [minutes, setMinutes] = React.useState(String(settings.values.alert_ack_minutes));
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const n = Number(minutes);
    if (!Number.isInteger(n) || n < 5 || n > 1440) {
      setErrors({ minutes: "Use whole minutes from 5 to 1440." });
      return;
    }
    setErrors({});
    void run(async () => {
      await api.updateSafetySettings({ alert_ack_minutes: n });
      notify.success("Safety settings saved");
    }, "We couldn't save those settings.");
  }

  return (
    <SectionCard
      title="Safety alerts"
      description="Alerts are always read and handled by people, never by a system."
    >
      <form onSubmit={submit} noValidate className="max-w-xl space-y-5">
        <Field
          label="Minutes a therapist has to acknowledge an alert"
          hint="Applies to new alerts from a student asking for a person to reach out and from a teacher's safety referral. Alerts that are late show up on your dashboard."
          error={errors.minutes}
        >
          {(p) => (
            <Input
              {...p}
              type="number"
              min={5}
              max={1440}
              className="max-w-xs"
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
            />
          )}
        </Field>
        <FixedRules rules={settings.fixed_rules} />
        {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
        <SaveButton pending={pending}>Save</SaveButton>
      </form>
    </SectionCard>
  );
}

export function SettingsView() {
  const [tab, setTab] = React.useState<"institution" | "notifications" | "safety">("institution");
  return (
    <>
      <PageHeader
        title="Settings"
        description="How MindMitra behaves for your institution. Changes are recorded in the audit log."
      />
      <SegmentedTabs
        label="Section"
        value={tab}
        onChange={setTab}
        options={[
          { value: "institution", label: "Institution" },
          { value: "notifications", label: "Notifications" },
          { value: "safety", label: "Safety" },
        ]}
      />
      {tab === "institution" && <InstitutionTab />}
      {tab === "notifications" && <NotificationsTab />}
      {tab === "safety" && <SafetyTab />}
    </>
  );
}
