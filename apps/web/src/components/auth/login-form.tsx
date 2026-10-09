"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AuthCard } from "@/components/auth/auth-card";
import { EmailField, PasswordField, SubmitButton } from "@/components/forms/fields";
import { InlineAlert } from "@/components/states/inline-alert";
import { Form } from "@/components/ui/form";
import { describeError, isApiError } from "@/lib/api/errors";
import { useAuth } from "@/lib/auth/auth-context";
import { safeNext } from "@/lib/auth/route-access";
import { emailSchema } from "@/lib/validation";

const schema = z.object({
  email: emailSchema(),
  password: z.string().min(1, "Enter your password"),
});
type Values = z.infer<typeof schema>;

export function LoginForm({ next }: { next?: string }) {
  const { login, status, user } = useAuth();
  const router = useRouter();
  const [formError, setFormError] = React.useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });
  const { isSubmitting } = form.formState;

  // One place decides where a signed-in person goes (also covers "already signed in").
  React.useEffect(() => {
    if (status === "authenticated" && user) router.replace(safeNext(next, user.role));
  }, [status, user, next, router]);

  async function onSubmit(values: Values) {
    setFormError(null);
    try {
      await login({ email: values.email, password: values.password });
    } catch (error) {
      form.resetField("password");
      setFormError(
        isApiError(error) && error.status === 401
          ? "That email and password don't match. Please check them and try again."
          : describeError(error),
      );
    }
  }

  const redirecting = status === "authenticated";

  return (
    <AuthCard
      title="Welcome back"
      description="Sign in to your MindMitra space."
      footer={
        <>
          <p>
            New student?{" "}
            <Link
              href="/register"
              className="font-medium text-primary underline underline-offset-4"
            >
              Create your account
            </Link>
          </p>
          <p>
            Staff accounts are set up by your institution. Use the link in your invitation email.
          </p>
        </>
      }
    >
      {formError && <InlineAlert tone="destructive">{formError}</InlineAlert>}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
          <EmailField<Values> name="email" label="Email" autoComplete="username" autoFocus />
          <PasswordField<Values> name="password" label="Password" />
          <div className="flex justify-end">
            <Link
              href="/forgot-password"
              className="text-sm font-medium text-primary underline underline-offset-4"
            >
              Forgot your password?
            </Link>
          </div>
          <SubmitButton
            pending={isSubmitting || redirecting}
            pendingLabel={redirecting ? "Opening your space…" : "Signing in…"}
            className="w-full"
          >
            Sign in
          </SubmitButton>
        </form>
      </Form>
    </AuthCard>
  );
}
