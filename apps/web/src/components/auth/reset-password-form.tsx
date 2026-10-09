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
import { isApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { applyApiErrors } from "@/lib/forms";
import { newPasswordSchema } from "@/lib/validation";

const schema = z
  .object({
    new_password: newPasswordSchema,
    confirm: z.string().min(1, "Type your new password again"),
  })
  .refine((v) => v.new_password === v.confirm, {
    path: ["confirm"],
    message: "The two passwords don't match",
  });
type Values = z.infer<typeof schema>;

/** Used for "forgot password" links and for first-time setup of invited staff accounts. */
export function ResetPasswordForm({ token }: { token?: string }) {
  const { manager } = useAuth();
  const [formError, setFormError] = React.useState<string | null>(null);
  const [done, setDone] = React.useState(false);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { new_password: "", confirm: "" },
  });

  if (!token) {
    return (
      <AuthCard title="This link isn't complete">
        <InlineAlert tone="warning">
          Open the link from your email again, or ask for a new one.
        </InlineAlert>
        <Button asChild className="w-full">
          <Link href="/forgot-password">Get a new link</Link>
        </Button>
      </AuthCard>
    );
  }

  async function onSubmit(values: Values) {
    setFormError(null);
    try {
      await manager.auth.resetPassword(token as string, values.new_password);
      setDone(true);
    } catch (error) {
      setFormError(
        isApiError(error) && error.status === 401
          ? "This link has expired or was already used. Please ask for a new one."
          : applyApiErrors(form, error, { password: "new_password" }),
      );
    }
  }

  if (done) {
    return (
      <AuthCard title="Password updated">
        <InlineAlert tone="success">
          Your password has been changed and you&apos;ve been signed out everywhere else.
        </InlineAlert>
        <Button asChild className="w-full">
          <Link href="/login">Sign in</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Choose a new password"
      description="Longer is stronger. A few random words work well."
    >
      {formError && <InlineAlert tone="destructive">{formError}</InlineAlert>}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
          <PasswordField<Values>
            name="new_password"
            label="New password"
            autoComplete="new-password"
            description="At least 12 characters."
            autoFocus
          />
          <PasswordField<Values>
            name="confirm"
            label="Confirm new password"
            autoComplete="new-password"
          />
          <SubmitButton
            pending={form.formState.isSubmitting}
            pendingLabel="Saving…"
            className="w-full"
          >
            Save new password
          </SubmitButton>
        </form>
      </Form>
    </AuthCard>
  );
}
