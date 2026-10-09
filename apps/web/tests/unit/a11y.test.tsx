import { render } from "@testing-library/react";
import { describe, it } from "vitest";

import { LoginForm } from "@/components/auth/login-form";
import { PortalLayout } from "@/components/auth/portal-layout";
import { RegisterForm } from "@/components/auth/register-form";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";
import { Showcase } from "@/components/design-system/showcase";
import { PortalOverview } from "@/components/portal/portal-overview";
import { ErrorState } from "@/components/states/error-state";
import AuthLayout from "@/app/(auth)/layout";
import HelpPage from "@/app/(public)/help/page";
import NotFound from "@/app/not-found";
import type { Role } from "@/lib/auth/roles";

import { expectNoA11yViolations } from "../helpers/a11y";
import { navigation } from "../helpers/navigation";
import { makeSession, renderWithApp } from "../helpers/render";
import { screen } from "@testing-library/react";

describe("accessibility (axe, WCAG 2.1 A/AA)", () => {
  it("sign-in page", async () => {
    const { container } = renderWithApp(
      <AuthLayout>
        <LoginForm />
      </AuthLayout>,
    );
    await expectNoA11yViolations(container);
  });

  it("sign-in page with an error showing", async () => {
    const { container } = renderWithApp(
      <AuthLayout>
        <LoginForm />
      </AuthLayout>,
      makeSession({
        "POST /auth/login": () =>
          new Response(JSON.stringify({ status: 401, detail: "no" }), { status: 401 }),
      }),
    );
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "a@test.example");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByRole("alert");
    await expectNoA11yViolations(container);
  });

  it("sign-in page with validation errors showing", async () => {
    const { container } = renderWithApp(<LoginForm />);
    const { default: userEvent } = await import("@testing-library/user-event");
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign in" }));
    await screen.findByText("Enter your email address");
    await expectNoA11yViolations(container);
  });

  it("register, forgot-password and reset-password pages", async () => {
    for (const ui of [
      <RegisterForm key="r" />,
      <ForgotPasswordForm key="f" />,
      <ResetPasswordForm key="p" token="tok-1234567890" />,
    ]) {
      const { container, unmount } = renderWithApp(<AuthLayout>{ui}</AuthLayout>);
      await expectNoA11yViolations(container);
      unmount();
    }
  });

  it.each<Role>(["student", "therapist", "teacher", "administrator"])(
    "%s portal shell",
    async (role) => {
      navigation.pathname = role === "administrator" ? "/admin" : `/${role}`;
      const { container } = renderWithApp(
        <PortalLayout role={role}>
          <PortalOverview
            role={role}
            description="Hello"
            planned={[{ title: "Soon", description: "Later" }]}
          />
        </PortalLayout>,
        makeSession({}, { signedInAs: role }),
      );
      await screen.findByRole("main");
      await expectNoA11yViolations(container);
    },
  );

  it("help page, 404 page and error state", async () => {
    for (const ui of [
      <HelpPage key="h" />,
      <NotFound key="n" />,
      <ErrorState key="e" onRetry={() => {}} reference="r" />,
    ]) {
      const { container, unmount } = render(ui);
      await expectNoA11yViolations(container);
      unmount();
    }
  });

  it("design-system showcase", async () => {
    const { container } = renderWithApp(<Showcase />);
    await expectNoA11yViolations(container);
  });
});
