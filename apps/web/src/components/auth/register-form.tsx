"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthCard } from "@/components/auth/auth-card";
import {
  CheckboxField,
  PasswordField,
  SelectField,
  SubmitButton,
  TextField,
} from "@/components/forms/fields";
import { InlineAlert } from "@/components/states/inline-alert";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { useAuth } from "@/lib/auth/auth-context";
import { applyApiErrors } from "@/lib/forms";

const YEARS_OF_STUDY = Array.from({ length: 8 }, (_, i) => ({
  value: String(i + 1),
  label: `Year ${i + 1}`,
}));

const schema = z.object({
  full_name: z.string().trim().min(1, "Enter your full name").max(200),
  email: z
    .string()
    .trim()
    .min(1, "Enter your institution email")
    .pipe(z.email("Enter a valid email address")),
  department_code: z.string().trim().min(1, "Enter your department code").max(20),
  student_number: z.string().trim().min(1, "Enter your student number").max(40),
  enrollment_year: z
    .string()
    .regex(/^\d{4}$/, "Enter a four-digit year")
    .refine((v) => Number(v) >= 1990 && Number(v) <= 2100, "Enter a year between 1990 and 2100"),
  year_of_study: z.string().min(1, "Choose your year of study"),
  password: z.string().min(12, "Use at least 12 characters").max(128, "Use at most 128 characters"),
  accept_terms: z.boolean().refine((v) => v, "Please confirm to create your account"),
});
type Values = z.infer<typeof schema>;

export function RegisterForm() {
  const { manager } = useAuth();
  const [formError, setFormError] = React.useState<string | null>(null);
  const [sentTo, setSentTo] = React.useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      full_name: "",
      email: "",
      department_code: "",
      student_number: "",
      enrollment_year: "",
      year_of_study: "",
      password: "",
      accept_terms: false,
    },
  });
  const { isSubmitting } = form.formState;

  async function onSubmit(values: Values) {
    setFormError(null);
    try {
      await manager.auth.register({
        email: values.email,
        password: values.password,
        full_name: values.full_name,
        department_code: values.department_code,
        student_number: values.student_number,
        enrollment_year: Number(values.enrollment_year),
        year_of_study: Number(values.year_of_study),
        accept_terms: true,
      });
      setSentTo(values.email);
    } catch (error) {
      setFormError(applyApiErrors(form, error));
    }
  }

  if (sentTo) {
    return (
      <AuthCard title="Check your email" description="One more step to open your space.">
        <InlineAlert tone="success">
          If {sentTo} can be registered, we&apos;ve sent a verification link to it. Open the link to
          finish setting up your account.
        </InlineAlert>
        <Button asChild variant="outline" className="w-full">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Create your account"
      description="Students sign up with their institution email. It only takes a minute."
      footer={
        <p>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary underline underline-offset-4">
            Sign in
          </Link>
        </p>
      }
    >
      {formError && <InlineAlert tone="destructive">{formError}</InlineAlert>}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
          <TextField<Values> name="full_name" label="Full name" autoComplete="name" autoFocus />
          <TextField<Values>
            name="email"
            label="Institution email"
            type="email"
            autoComplete="email"
            inputMode="email"
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField<Values> name="department_code" label="Department code" autoComplete="off" />
            <TextField<Values> name="student_number" label="Student number" autoComplete="off" />
            <TextField<Values>
              name="enrollment_year"
              label="Enrollment year"
              inputMode="numeric"
              autoComplete="off"
              placeholder="e.g. 2024"
            />
            <SelectField<Values>
              name="year_of_study"
              label="Year of study"
              options={YEARS_OF_STUDY}
            />
          </div>
          <PasswordField<Values>
            name="password"
            label="Password"
            autoComplete="new-password"
            description="At least 12 characters. A few random words work well."
          />
          <CheckboxField<Values>
            name="accept_terms"
            label="I agree to the MindMitra terms of use and privacy notice, and I understand MindMitra is a support tool, not an emergency service."
          />
          <SubmitButton
            pending={isSubmitting}
            pendingLabel="Creating your account…"
            className="w-full"
          >
            Create account
          </SubmitButton>
        </form>
      </Form>
    </AuthCard>
  );
}
