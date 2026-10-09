import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";
import { RegisterForm } from "@/components/auth/register-form";
import { ResetPasswordForm } from "@/components/auth/reset-password-form";
import { VerifyEmailView } from "@/components/auth/verify-email-view";

import { json, makeSession, problem, renderWithApp } from "../helpers/render";

describe("RegisterForm", () => {
  async function fillValid(user: ReturnType<typeof userEvent.setup>) {
    await user.type(screen.getByLabelText("Full name"), "Asha Verma");
    await user.type(screen.getByLabelText("Institution email"), "asha@synthetic.example");
    await user.type(screen.getByLabelText("Department code"), "CSE");
    await user.type(screen.getByLabelText("Student number"), "S-1001");
    await user.type(screen.getByLabelText("Enrollment year"), "2024");
    await user.click(screen.getByRole("combobox", { name: "Year of study" }));
    await user.click(await screen.findByRole("option", { name: "Year 2" }));
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("checkbox"));
  }

  it("requires every field and the terms checkbox", async () => {
    renderWithApp(<RegisterForm />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Enter your full name")).toBeInTheDocument();
    expect(screen.getByText("Enter your institution email")).toBeInTheDocument();
    expect(screen.getByText("Enter a four-digit year")).toBeInTheDocument();
    expect(screen.getByText("Use at least 12 characters")).toBeInTheDocument();
    expect(screen.getByText("Please confirm to create your account")).toBeInTheDocument();
  });

  it("submits the API's exact shape and then asks the student to check their email", async () => {
    const bodies: unknown[] = [];
    renderWithApp(
      <RegisterForm />,
      makeSession({
        "POST /auth/register": ({ body }) => {
          bodies.push(body);
          return json({ status: "verification_sent" }, 202);
        },
      }),
    );
    const user = userEvent.setup();
    await fillValid(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Check your email" })).toBeInTheDocument();
    expect(bodies).toEqual([
      {
        email: "asha@synthetic.example",
        password: "correct horse battery",
        full_name: "Asha Verma",
        department_code: "CSE",
        student_number: "S-1001",
        enrollment_year: 2024,
        year_of_study: 2,
        accept_terms: true,
      },
    ]);
  });

  it("shows the API's field errors next to the fields", async () => {
    renderWithApp(
      <RegisterForm />,
      makeSession({
        "POST /auth/register": () =>
          problem(422, "The password does not meet the policy.", {
            errors: [{ loc: ["body", "password"], msg: "is too common or too repetitive" }],
          }),
      }),
    );
    const user = userEvent.setup();
    await fillValid(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Is too common or too repetitive")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(/check the highlighted fields/i)).toBeInTheDocument();
  });
});

describe("ForgotPasswordForm", () => {
  it("shows the same neutral confirmation whatever the API says about the account", async () => {
    const bodies: unknown[] = [];
    renderWithApp(
      <ForgotPasswordForm />,
      makeSession({
        "POST /auth/password/forgot": ({ body }) => {
          bodies.push(body);
          return json({ status: "if_the_account_exists_a_link_was_sent" }, 202);
        },
      }),
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "nobody@test.example");
    await user.click(screen.getByRole("button", { name: "Send reset link" }));
    expect(await screen.findByText(/If an account exists for that email/)).toBeInTheDocument();
    expect(bodies).toEqual([{ email: "nobody@test.example" }]);
  });
});

describe("ResetPasswordForm", () => {
  it("explains an incomplete link", () => {
    renderWithApp(<ResetPasswordForm />);
    expect(screen.getByText("This link isn't complete")).toBeInTheDocument();
  });

  it("checks the two passwords match before calling the API", async () => {
    renderWithApp(<ResetPasswordForm token="tok-1234567890" />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "correct horse battery");
    await user.type(screen.getByLabelText("Confirm new password"), "something else entirely");
    await user.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByText("The two passwords don't match")).toBeInTheDocument();
  });

  it("sets the new password with the token", async () => {
    const bodies: unknown[] = [];
    renderWithApp(
      <ResetPasswordForm token="tok-1234567890" />,
      makeSession({
        "POST /auth/password/reset": ({ body }) => {
          bodies.push(body);
          return json({ status: "password_updated" });
        },
      }),
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "correct horse battery");
    await user.type(screen.getByLabelText("Confirm new password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByRole("heading", { name: "Password updated" })).toBeInTheDocument();
    expect(bodies).toEqual([{ token: "tok-1234567890", new_password: "correct horse battery" }]);
  });

  it("says so when the link has expired", async () => {
    renderWithApp(
      <ResetPasswordForm token="tok-1234567890" />,
      makeSession({ "POST /auth/password/reset": () => problem(401, "Invalid or expired token.") }),
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "correct horse battery");
    await user.type(screen.getByLabelText("Confirm new password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("expired or was already used");
  });

  it("maps the API's `password` field error onto the new-password field", async () => {
    renderWithApp(
      <ResetPasswordForm token="tok-1234567890" />,
      makeSession({
        "POST /auth/password/reset": () =>
          problem(422, "The password does not meet the policy.", {
            errors: [{ loc: ["body", "password"], msg: "is too common or too repetitive" }],
          }),
      }),
    );
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("New password"), "aaaaaaaaaaaaaaaa");
    await user.type(screen.getByLabelText("Confirm new password"), "aaaaaaaaaaaaaaaa");
    await user.click(screen.getByRole("button", { name: "Save new password" }));
    expect(await screen.findByText("Is too common or too repetitive")).toBeInTheDocument();
  });
});

describe("VerifyEmailView", () => {
  it("verifies the token exactly once and offers sign-in", async () => {
    let calls = 0;
    renderWithApp(
      <VerifyEmailView token="tok-1234567890" />,
      makeSession({
        "POST /auth/verify-email": () => {
          calls += 1;
          return json({ status: "verified" });
        },
      }),
    );
    expect(await screen.findByRole("heading", { name: "Email verified" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
    expect(calls).toBe(1);
  });

  it("reports a bad or used token", async () => {
    renderWithApp(
      <VerifyEmailView token="tok-1234567890" />,
      makeSession({ "POST /auth/verify-email": () => problem(401, "Invalid token") }),
    );
    expect(
      await screen.findByText("This link has expired or was already used."),
    ).toBeInTheDocument();
  });

  it("handles a missing token without calling the API", async () => {
    const session = makeSession();
    renderWithApp(<VerifyEmailView />, session);
    await waitFor(() => expect(screen.getByText("This link isn't complete")).toBeInTheDocument());
    expect(session.api.mock).not.toHaveBeenCalled();
  });
});
