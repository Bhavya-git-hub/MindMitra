"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthCard } from "@/components/auth/auth-card";
import { PasswordField, SubmitButton } from "@/components/forms/fields";
import { InlineAlert } from "@/components/states/inline-alert";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { describeError, isApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";

const schema = z.object({
  password: z.string().min(1, "Enter the password you chose when you registered"),
});
type Values = z.infer<typeof schema>;

/**
 * Confirms the one-time token from the verification email together with the password chosen at
 * registration. Asking for the password means a link sent because someone else registered this
 * address cannot switch on their account.
 */
export function VerifyEmailView({ token }: { token?: string }) {
  const { manager } = useAuth();
  const [done, setDone] = React.useState(false);
  const [formError, setFormError] = React.useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { password: "" } });

  if (!token) {
    return (
      <AuthCard title="This link isn't complete">
        <InlineAlert tone="warning">Open the link from your verification email again.</InlineAlert>
      </AuthCard>
    );
  }

  async function onSubmit({ password }: Values) {
    if (!token) return;
    setFormError(null);
    try {
      await manager.auth.verifyEmail(token, password);
      setDone(true);
    } catch (error) {
      setFormError(
        isApiError(error) && (error.status === 401 || error.status === 400)
          ? "That password doesn't match, or this link has expired or was already used. If you didn't register, you can ignore the email."
          : describeError(error),
      );
    }
  }

  if (done) {
    return (
      <AuthCard title="Email verified">
        <InlineAlert tone="success">Thank you. Your account is ready.</InlineAlert>
        <Button asChild className="w-full">
          <Link href="/login">Sign in</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Verify your email"
      description="Enter the password you chose when you registered to switch on your account."
      footer={
        <Link href="/register" className="font-medium text-primary underline underline-offset-4">
          Register again
        </Link>
      }
    >
      {formError && <InlineAlert tone="destructive">{formError}</InlineAlert>}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
          <PasswordField<Values> name="password" label="Password" autoFocus />
          <SubmitButton
            pending={form.formState.isSubmitting}
            pendingLabel="Verifying…"
            className="w-full"
          >
            Verify email
          </SubmitButton>
        </form>
      </Form>
    </AuthCard>
  );
}
