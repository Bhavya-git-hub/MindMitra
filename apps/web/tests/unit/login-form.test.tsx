import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LoginForm } from "@/components/auth/login-form";

import { navigation } from "../helpers/navigation";
import { json, makeSession, me, problem, renderWithApp, tokens } from "../helpers/render";

async function fillAndSubmit(
  email = "asha.verma@test.example",
  password = "correct horse battery",
) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Email"), email);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

function loginSession(role: Parameters<typeof tokens>[0], calls: unknown[] = []) {
  return makeSession({
    "POST /auth/login": ({ body }) => {
      calls.push(body);
      return json(tokens(role));
    },
    "GET /me": () => json(me(role)),
  });
}

describe("LoginForm", () => {
  it("validates before calling the API", async () => {
    const calls: unknown[] = [];
    renderWithApp(<LoginForm />, loginSession("student", calls));
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your email address")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("rejects a malformed email", async () => {
    renderWithApp(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "x");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
  });

  it.each([
    ["student", "/student"],
    ["therapist", "/therapist"],
    ["teacher", "/teacher"],
    ["administrator", "/admin"],
  ] as const)("signs in a %s and goes to %s", async (role, home) => {
    const calls: unknown[] = [];
    renderWithApp(<LoginForm />, loginSession(role, calls));
    await fillAndSubmit();
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith(home));
    expect(calls).toEqual([
      { email: "asha.verma@test.example", password: "correct horse battery" },
    ]);
  });

  it("returns to the page the person was heading to, inside their own portal", async () => {
    renderWithApp(<LoginForm next="/student/account" />, loginSession("student"));
    await fillAndSubmit();
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/student/account"));
  });

  it.each(["//evil.example", "https://evil.example", "/admin"])(
    "ignores an unsafe or foreign next=%s",
    async (next) => {
      renderWithApp(<LoginForm next={next} />, loginSession("student"));
      await fillAndSubmit();
      await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/student"));
    },
  );

  it("shows one generic message for bad credentials, clears the password and stays put", async () => {
    renderWithApp(
      <LoginForm />,
      makeSession({ "POST /auth/login": () => problem(401, "Invalid email or password.") }),
    );
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That email and password don't match",
    );
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  it("explains rate limiting and network failures kindly", async () => {
    const limited = renderWithApp(
      <LoginForm />,
      makeSession({
        "POST /auth/login": () => problem(429, "Too many requests", {}, { "Retry-After": "30" }),
      }),
    );
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("wait about 30 seconds");
    limited.unmount();
  });

  it("can show and hide the password", async () => {
    renderWithApp(<LoginForm />);
    const user = userEvent.setup();
    const field = screen.getByLabelText("Password");
    expect(field).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(field).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends an already signed-in person straight to their portal", async () => {
    renderWithApp(<LoginForm />, makeSession({}, { signedInAs: "teacher" }));
    // AuthProvider bootstraps the stored session, then the form redirects.
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/teacher"));
  });

  it("links to registration and password reset", () => {
    renderWithApp(<LoginForm />);
    expect(screen.getByRole("link", { name: "Create your account" })).toHaveAttribute(
      "href",
      "/register",
    );
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
  });
});
