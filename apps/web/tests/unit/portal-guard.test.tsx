import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Users } from "lucide-react";
import { describe, expect, it } from "vitest";

import { AccountView } from "@/components/account/account-view";
import { PortalLayout } from "@/components/auth/portal-layout";
import { PortalOverview } from "@/components/portal/portal-overview";
import type { Role } from "@/lib/auth/roles";
import { NAVIGATION } from "@/lib/navigation";

import { navigation } from "../helpers/navigation";
import { json, makeSession, me, problem, renderWithApp, tokens } from "../helpers/render";

const PLANNED = [{ title: "Daily check-in", description: "A short note." }];

function portal(role: Role) {
  return (
    <PortalLayout role={role}>
      <PortalOverview role={role} description="Hello" planned={PLANNED} />
    </PortalLayout>
  );
}

describe("portal guard (AuthGate)", () => {
  it("shows a loading state, not the portal, while the session is restored", () => {
    navigation.pathname = "/student";
    renderWithApp(portal("student"), makeSession({}, { signedInAs: "student" }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking your session");
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
  });

  it("renders the portal for the matching role", async () => {
    navigation.pathname = "/student";
    renderWithApp(portal("student"), makeSession({}, { signedInAs: "student" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome, Asha" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("sends a signed-out visitor to /login and remembers the page", async () => {
    navigation.pathname = "/therapist/account";
    renderWithApp(portal("therapist"));
    await waitFor(() =>
      expect(navigation.router.replace).toHaveBeenCalledWith("/login?next=%2Ftherapist%2Faccount"),
    );
    expect(screen.queryByText("Welcome")).not.toBeInTheDocument();
  });

  it("shows a retry, and does not redirect, when the session cannot be checked", async () => {
    navigation.pathname = "/student";
    let up = false;
    const outage = makeSession(
      {
        "POST /auth/refresh": () => (up ? json(tokens("student", 2)) : problem(503, "down")),
        "GET /me": () => json(me("student")),
      },
      { signedInAs: "student" },
    );
    renderWithApp(portal("student"), outage);

    expect(await screen.findByText("We couldn't check your session")).toBeInTheDocument();
    expect(navigation.router.replace).not.toHaveBeenCalled();

    up = true;
    await userEvent.setup().click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome, Asha" }),
    ).toBeInTheDocument();
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  it.each<[Role, Role, string]>([
    ["administrator", "student", "/student"],
    ["student", "teacher", "/teacher"],
    ["teacher", "therapist", "/therapist"],
    ["therapist", "administrator", "/admin"],
  ])("never shows the %s portal to a %s: redirects to %s", async (portalRole, userRole, home) => {
    navigation.pathname = "/x";
    renderWithApp(portal(portalRole), makeSession({}, { signedInAs: userRole }));
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith(home));
    expect(screen.queryByRole("main")).not.toBeInTheDocument();
    expect(screen.queryByText(PLANNED[0]!.title)).not.toBeInTheDocument();
  });
});

describe("shell navigation", () => {
  it("shows the role's menu, marks the current page and disables unbuilt pages", async () => {
    navigation.pathname = "/student/account";
    renderWithApp(portal("student"), makeSession({}, { signedInAs: "student" }));
    await screen.findByRole("main");

    const nav = screen.getByRole("navigation", { name: "Student navigation" });
    expect(within(nav).getByRole("link", { name: "Account" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "Daily check-in" })).toHaveAttribute(
      "href",
      "/student/check-in",
    );
  });

  it("shows pages that are not built yet as disabled, not as links", async () => {
    // every portal page is built now, so list a planned one for the duration of this test
    const planned = { label: "Planned page", href: "/admin/planned", icon: Users, soon: true };
    NAVIGATION.administrator.push(planned);
    try {
      navigation.pathname = "/admin/account";
      renderWithApp(portal("administrator"), makeSession({}, { signedInAs: "administrator" }));
      await screen.findByRole("main");
      const nav = screen.getByRole("navigation", { name: "Administrator navigation" });
      expect(within(nav).queryByRole("link", { name: /Planned page/ })).not.toBeInTheDocument();
      expect(within(nav).getAllByText("Soon").length).toBeGreaterThan(0);
      expect(within(nav).getByRole("link", { name: "Audit log" })).toHaveAttribute(
        "href",
        "/admin/audit",
      );
    } finally {
      NAVIGATION.administrator.pop();
    }
  });

  it("has a skip link, a persistent Get help button for students, and a disclaimer", async () => {
    navigation.pathname = "/student";
    renderWithApp(portal("student"), makeSession({}, { signedInAs: "student" }));
    await screen.findByRole("main");
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
      "href",
      "#main-content",
    );
    expect(screen.getAllByRole("link", { name: /Get help/ })[0]).toHaveAttribute("href", "/help");
    expect(screen.getByText(/not a diagnosis or medical advice/)).toBeInTheDocument();
  });

  it("does not show Get help or the disclaimer in staff portals", async () => {
    navigation.pathname = "/teacher";
    renderWithApp(portal("teacher"), makeSession({}, { signedInAs: "teacher" }));
    await screen.findByRole("main");
    expect(screen.queryByRole("link", { name: /Get help/ })).not.toBeInTheDocument();
  });
});

describe("sign out", () => {
  it("asks first, then signs out, clears the pass, and returns to /login", async () => {
    navigation.pathname = "/student/account";
    const session = makeSession({}, { signedInAs: "student" });
    renderWithApp(
      <PortalLayout role="student">
        <AccountView />
      </PortalLayout>,
      session,
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: "Account" });
    expect(screen.getByText("asha.verma@test.example")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(session.api.calls.some((c) => c.path === "/auth/logout")).toBe(false);

    await user.click(within(dialog).getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/login"));
    expect(session.api.calls.some((c) => c.path === "/auth/logout")).toBe(true);
    expect(session.syncPass).toHaveBeenLastCalledWith(null);
    expect(await screen.findByText("You're signed out")).toBeInTheDocument();
    // After an explicit sign-out the guard must not add a next= to the login URL.
    const targets = navigation.router.replace.mock.calls.map(([url]) => url);
    expect(targets.length).toBeGreaterThan(0);
    expect(new Set(targets)).toEqual(new Set(["/login"]));
  });

  it("stays signed in when the person cancels", async () => {
    navigation.pathname = "/student/account";
    const session = makeSession({}, { signedInAs: "student" });
    renderWithApp(
      <PortalLayout role="student">
        <AccountView />
      </PortalLayout>,
      session,
    );
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: "Account" });
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(session.api.calls.some((c) => c.path === "/auth/logout")).toBe(false);
    expect(navigation.router.replace).not.toHaveBeenCalled();
  });

  it("signs out from the account menu in the header", async () => {
    navigation.pathname = "/teacher";
    const session = makeSession({}, { signedInAs: "teacher" });
    renderWithApp(portal("teacher"), session);
    const user = userEvent.setup();
    await screen.findByRole("main");
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(navigation.router.replace).toHaveBeenCalledWith("/login"));
    expect(session.api.calls.some((c) => c.path === "/auth/logout")).toBe(true);
  });
});
