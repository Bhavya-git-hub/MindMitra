"use client";

import * as React from "react";

import { SectionCard } from "@/components/cards/section-card";
import { PageHeader } from "@/components/layout/page-header";
import { InlineAlert } from "@/components/states/inline-alert";
import { DataView } from "@/components/student/data-view";
import { SaveButton, useSubmit } from "@/components/student/form-bits";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { TherapistProfile } from "@/lib/api/therapist-schemas";
import { formatShortDate } from "@/lib/format";
import { useQuery } from "@/lib/hooks/use-query";
import { useTherapistApi } from "@/lib/hooks/use-therapist-api";
import { notify } from "@/lib/toast";

import { VerificationBadge } from "./shared";

const splitList = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

function ProfileForm({
  profile,
  onSaved,
}: {
  profile: TherapistProfile;
  onSaved: () => Promise<void>;
}) {
  const api = useTherapistApi();
  const [bio, setBio] = React.useState(profile.bio ?? "");
  const [specialties, setSpecialties] = React.useState(profile.specialties.join(", "));
  const [languages, setLanguages] = React.useState(profile.languages.join(", "));
  const [accepting, setAccepting] = React.useState(profile.accepting_new_students);
  const [caseload, setCaseload] = React.useState(String(profile.max_caseload));
  const [caseloadError, setCaseloadError] = React.useState<string>();
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const max = Number(caseload);
    if (!Number.isInteger(max) || max < 1 || max > 500) {
      setCaseloadError("Enter a whole number from 1 to 500.");
      return;
    }
    setCaseloadError(undefined);
    void run(async () => {
      await api.updateProfile({
        bio: bio.trim(),
        specialties: splitList(specialties),
        languages: splitList(languages),
        accepting_new_students: accepting,
        max_caseload: max,
      });
      notify.success("Profile saved", "Students see this when they look for a therapist.");
      await onSaved();
    });
  }

  return (
    <form onSubmit={submit} className="space-y-5" noValidate>
      <div className="space-y-2">
        <Label htmlFor="bio">About you</Label>
        <Textarea
          id="bio"
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          maxLength={2000}
          rows={5}
          aria-describedby="bio-hint"
        />
        <p id="bio-hint" className="text-sm text-muted-foreground">
          Shown to students who search for a therapist. Keep it warm and plain.
        </p>
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="specialties">Focus areas</Label>
          <Input
            id="specialties"
            value={specialties}
            onChange={(e) => setSpecialties(e.target.value)}
            aria-describedby="specialties-hint"
          />
          <p id="specialties-hint" className="text-sm text-muted-foreground">
            Separate with commas, up to 8.
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="languages">Languages</Label>
          <Input
            id="languages"
            value={languages}
            onChange={(e) => setLanguages(e.target.value)}
            aria-describedby="languages-hint"
          />
          <p id="languages-hint" className="text-sm text-muted-foreground">
            Separate with commas.
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="caseload">Most students at one time</Label>
          <Input
            id="caseload"
            inputMode="numeric"
            value={caseload}
            onChange={(e) => setCaseload(e.target.value)}
            aria-invalid={caseloadError ? true : undefined}
            aria-describedby={caseloadError ? "caseload-error" : undefined}
          />
          {caseloadError && (
            <p id="caseload-error" role="alert" className="text-sm text-destructive">
              {caseloadError}
            </p>
          )}
        </div>
        <div className="flex items-end">
          <label className="flex min-h-10 items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={accepting}
              onChange={(e) => setAccepting(e.target.checked)}
              className="size-4 accent-[var(--primary)]"
            />
            I&apos;m taking new students
          </label>
        </div>
      </div>
      {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
      <SaveButton pending={pending}>Save profile</SaveButton>
    </form>
  );
}

function VerificationCard({
  profile,
  onSaved,
}: {
  profile: TherapistProfile;
  onSaved: () => Promise<void>;
}) {
  const api = useTherapistApi();
  const [number, setNumber] = React.useState(profile.licence_number);
  const [body, setBody] = React.useState(profile.licence_body ?? "");
  const [expires, setExpires] = React.useState(profile.licence_expires_on ?? "");
  const [numberError, setNumberError] = React.useState<string>();
  const { pending, error, run } = useSubmit();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (number.trim().length < 3) {
      setNumberError("Enter your registration or licence number.");
      return;
    }
    setNumberError(undefined);
    void run(async () => {
      await api.submitVerification({
        licence_number: number.trim(),
        licence_body: body.trim() || undefined,
        licence_expires_on: expires || undefined,
      });
      notify.success("Sent for verification", "An administrator will review your details.");
      await onSaved();
    }, "We couldn't send your details. Check the licence date and try again.");
  }

  const status = profile.verification_status;
  return (
    <SectionCard
      title="Professional verification"
      description="Students' information stays closed until an administrator has verified your registration."
      action={<VerificationBadge status={status} label={profile.verification_label} />}
    >
      <div className="space-y-5">
        {status === "verified" && (
          <InlineAlert tone="success" title="You're verified">
            {profile.verified_at ? `Since ${formatShortDate(profile.verified_at)}. ` : ""}
            {profile.licence_expires_on
              ? `Your licence runs to ${formatShortDate(profile.licence_expires_on)}.`
              : ""}
          </InlineAlert>
        )}
        {status === "pending" && (
          <InlineAlert tone="info" title="Waiting for an administrator">
            You can set up your profile and availability now. Students can find you, and you can see
            your students, once you&apos;re verified.
          </InlineAlert>
        )}
        {(status === "rejected" || status === "expired") && (
          <InlineAlert tone="warning" title={profile.verification_label}>
            {profile.verification_note
              ? `Note from the administrator: ${profile.verification_note} `
              : ""}
            Send updated details to be reviewed again.
          </InlineAlert>
        )}
        <form onSubmit={submit} className="grid gap-5 sm:grid-cols-3" noValidate>
          <div className="space-y-2">
            <Label htmlFor="licence">Registration number</Label>
            <Input
              id="licence"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              aria-invalid={numberError ? true : undefined}
              aria-describedby={numberError ? "licence-error" : undefined}
            />
            {numberError && (
              <p id="licence-error" role="alert" className="text-sm text-destructive">
                {numberError}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="licence-body">Registered with</Label>
            <Input id="licence-body" value={body} onChange={(e) => setBody(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="licence-expiry">Valid until</Label>
            <Input
              id="licence-expiry"
              type="date"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          </div>
          <div className="space-y-3 sm:col-span-3">
            {status === "verified" && (
              <p className="text-sm text-muted-foreground">
                Sending new details puts you back in review until they&apos;re checked.
              </p>
            )}
            {error && <InlineAlert tone="destructive">{error}</InlineAlert>}
            <SaveButton pending={pending} variant="outline">
              Send for verification
            </SaveButton>
          </div>
        </form>
      </div>
    </SectionCard>
  );
}

export function ProfileView() {
  const api = useTherapistApi();
  const profile = useQuery("therapist-profile", () => api.profile());

  return (
    <>
      <PageHeader
        title="Profile"
        description="How students see you, and your professional status."
      />
      <DataView query={profile}>
        {(p) => (
          <>
            <VerificationCard profile={p} onSaved={profile.reload} />
            <SectionCard title={p.full_name} description={p.email}>
              <ProfileForm profile={p} onSaved={profile.reload} />
            </SectionCard>
          </>
        )}
      </DataView>
    </>
  );
}
