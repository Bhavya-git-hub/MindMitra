"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthCard } from "@/components/auth/auth-card";
import { EmailField, SubmitButton } from "@/components/forms/fields";
import { InlineAlert } from "@/components/states/inline-alert";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { describeError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { emailSchema } from "@/lib/validation";

const schema = z.object({
  email: emailSchema(),
});
type Values = z.infer<typeof schema>;

export function ForgotPasswordForm() {
  const { manager } = useAuth();
  const [formError, setFormError] = React.useState<string | null>(null);
  const [sent, setSent] = React.useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: "" } });

  async function onSubmit({ email }: Values) {
    setFormError(null);
    try {
      await manager.auth.forgotPassword(email);
      setSent(true);
    } catch (error) {
      setFormError(describeError(error));
    }
  }

  if (sent) {
    return (
      <AuthCard title="Check your email">
        <InlineAlert tone="success">
          If an account exists for that email, we&apos;ve sent a link to choose a new password. It
          can take a few minutes to arrive.
        </InlineAlert>
        <Button asChild variant="outline" className="w-full">
          <Link href="/login">Back to sign in</Link>
        </Button>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Reset your password"
      description="Enter your email and we'll send you a link to choose a new one."
      footer={
        <Link href="/login" className="font-medium text-primary underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      {formError && <InlineAlert tone="destructive">{formError}</InlineAlert>}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
          <EmailField<Values> name="email" label="Email" autoFocus />
          <SubmitButton
            pending={form.formState.isSubmitting}
            pendingLabel="Sending…"
            className="w-full"
          >
            Send reset link
          </SubmitButton>
        </form>
      </Form>
    </AuthCard>
  );
}
