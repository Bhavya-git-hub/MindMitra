import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import {
  AdminResourcesView,
  EditResourceView,
  NewResourceView,
} from "@/components/admin/resources-views";
import { SettingsView } from "@/components/admin/settings-view";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import { navigation } from "../helpers/navigation";
import {
  CONTACT,
  RESOURCE,
  adminSession,
  contact,
  notificationSettings,
  resource,
  safetySettings,
} from "../helpers/admin-data";

beforeEach(() => navigation.reset());

describe("resources", () => {
  const library = [
    resource(),
    resource({
      id: "0192d000-0000-7000-8000-0000000000c1",
      title: "Grounding",
      is_published: true,
      source: "global",
      editable: false,
      reviewed_at: "2026-09-01T00:00:00Z",
    }),
  ];

  it("lists drafts and published items, and marks shipped ones read only", async () => {
    const session = adminSession({ "GET /admin/resources": () => json(library) });
    const { container } = renderWithApp(<AdminResourcesView />, session);
    expect(await screen.findByText("2 resources")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Box breathing" })).toHaveAttribute(
      "href",
      `/admin/resources/${RESOURCE}`,
    );
    expect(screen.queryByRole("link", { name: "Grounding" })).not.toBeInTheDocument();
    expect(screen.getByText("Read only")).toBeInTheDocument();
    expect(screen.getAllByText("Shipped with MindMitra").length).toBeGreaterThan(0);
    // Only the editable item has publish and delete controls.
    expect(screen.getAllByRole("button", { name: /^(Publish|Withdraw)\s*[A-Z]/ })).toHaveLength(1);
    await expectNoA11yViolations(container);
  });

  it("publishes a draft and says so", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      "GET /admin/resources": () => json(library),
      [`PATCH /admin/resources/${RESOURCE}/publication`]: (call) => {
        patches.push(call.body);
        return json(resource({ is_published: true }));
      },
    });
    renderWithApp(<AdminResourcesView />, session);
    await user.click(await screen.findByRole("button", { name: /^Publish\s*Box breathing/ }));
    await waitFor(() => expect(patches).toEqual([{ published: true }]));
    expect(
      await screen.findByText("Published", { selector: "[data-sonner-toast] *" }),
    ).toBeInTheDocument();
  });

  it("filters by status and type through the API", async () => {
    const user = userEvent.setup();
    const session = adminSession({ "GET /admin/resources": () => json([]) });
    renderWithApp(<AdminResourcesView />, session);
    expect(await screen.findByText("Nothing here yet")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Drafts" }));
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.query.get("published") === "false")).toBe(true),
    );
    await user.click(screen.getByRole("button", { name: "Shipped with MindMitra" }));
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.query.get("source") === "global")).toBe(true),
    );
    await user.selectOptions(screen.getByLabelText("Type"), "video");
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.query.get("resource_type") === "video")).toBe(true),
    );
  });

  it("deletes only after confirmation", async () => {
    const user = userEvent.setup();
    let deleted = 0;
    const session = adminSession({
      "GET /admin/resources": () => json([resource()]),
      [`DELETE /admin/resources/${RESOURCE}`]: () => {
        deleted += 1;
        return new Response(null, { status: 204 });
      },
    });
    renderWithApp(<AdminResourcesView />, session);
    await user.click(await screen.findByRole("button", { name: /Delete/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(deleted).toBe(0);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toBe(1));
  });

  it("validates a new resource, then creates it as a draft", async () => {
    const user = userEvent.setup();
    const posts: unknown[] = [];
    const session = adminSession({
      "POST /admin/resources": (call) => {
        posts.push(call.body);
        return json(resource(), 201);
      },
    });
    const { container } = renderWithApp(<NewResourceView />, session);
    await user.click(screen.getByRole("button", { name: "Add resource" }));
    expect(screen.getByText("Enter a title.")).toBeInTheDocument();
    expect(screen.getByText("Add a short summary.")).toBeInTheDocument();
    expect(screen.getByText("Add some text or a link.")).toBeInTheDocument();
    expect(posts).toEqual([]);
    await expectNoA11yViolations(container);

    await user.type(screen.getByLabelText("Title"), "Walking break");
    await user.type(screen.getByLabelText("Short summary"), "A short walk helps.");
    await user.type(screen.getByLabelText("Link (optional)"), "http://insecure.example");
    await user.click(screen.getByRole("button", { name: "Add resource" }));
    expect(screen.getByText("Links must start with https://")).toBeInTheDocument();

    const link = screen.getByLabelText("Link (optional)");
    await user.clear(link);
    await user.type(link, "https://calm.example/walk");
    await user.type(screen.getByLabelText("Tags"), "calm, outdoors");
    await user.click(screen.getByRole("button", { name: "Add resource" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      title: "Walking break",
      url: "https://calm.example/walk",
      tags: ["calm", "outdoors"],
      resource_type: "article",
      publish: false,
    });
    await waitFor(() => expect(navigation.router.push).toHaveBeenCalledWith("/admin/resources"));
  });

  it("publishes straight away when ticked", async () => {
    const user = userEvent.setup();
    const posts: Array<Record<string, unknown>> = [];
    const session = adminSession({
      "POST /admin/resources": (call) => {
        posts.push(call.body as Record<string, unknown>);
        return json(resource(), 201);
      },
    });
    renderWithApp(<NewResourceView />, session);
    await user.type(screen.getByLabelText("Title"), "Sleep hygiene");
    await user.type(screen.getByLabelText("Short summary"), "Habits for sleep.");
    await user.type(screen.getByLabelText("Text"), "Keep a regular schedule.");
    await user.click(screen.getByRole("checkbox", { name: "Publish straight away" }));
    await user.click(screen.getByRole("button", { name: "Add resource" }));
    await waitFor(() => expect(posts[0]?.publish).toBe(true));
  });

  it("edits an existing resource with PUT", async () => {
    const user = userEvent.setup();
    const puts: unknown[] = [];
    const session = adminSession({
      [`GET /admin/resources/${RESOURCE}`]: () => json(resource()),
      [`PUT /admin/resources/${RESOURCE}`]: (call) => {
        puts.push(call.body);
        return json(resource());
      },
    });
    renderWithApp(<EditResourceView id={RESOURCE} />, session);
    const title = await screen.findByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Box breathing (short)");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ title: "Box breathing (short)", tags: ["calm"] });
  });

  it("does not offer a form for a resource that ships with the product", async () => {
    const session = adminSession({
      [`GET /admin/resources/${RESOURCE}`]: () =>
        json(resource({ editable: false, source: "global" })),
    });
    renderWithApp(<EditResourceView id={RESOURCE} />, session);
    expect(
      await screen.findByText(/ships with MindMitra and can.t be changed here/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Title")).not.toBeInTheDocument();
  });
});

describe("settings", () => {
  const institution = {
    id: "0192d000-0000-7000-8000-0000000000f0",
    name: "Synthetic College",
    slug: "synthetic",
    region: "in",
    email_domains: ["college.example"],
  };
  const common = {
    "GET /admin/config": () => json(institution),
    "GET /admin/settings/notifications": () => json(notificationSettings()),
    "GET /admin/settings/safety": () => json(safetySettings()),
    "GET /admin/settings/crisis-contacts": () =>
      json([
        contact(),
        contact({
          id: "0192d000-0000-7000-8000-0000000000d1",
          label: "National helpline",
          kind: "helpline",
          editable: false,
        }),
      ]),
  };

  it("saves the institution name and sign-up domains", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      ...common,
      "PATCH /admin/config": (call) => {
        patches.push(call.body);
        return json(institution);
      },
    });
    const { container } = renderWithApp(<SettingsView />, session);
    const domains = await screen.findByLabelText("Email domains for student sign-up");
    await expectNoA11yViolations(container);
    await user.clear(domains);
    await user.type(domains, "not a domain");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText(/Use domain names like college.example/)).toBeInTheDocument();
    expect(patches).toEqual([]);
    await user.clear(domains);
    await user.type(domains, "College.example, mail.college.example");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(patches).toEqual([
        { name: "Synthetic College", email_domains: ["college.example", "mail.college.example"] },
      ]),
    );
  });

  it("is honest that reminders and email are saved but not yet sent", async () => {
    const user = userEvent.setup();
    renderWithApp(<SettingsView />, adminSession(common));
    await user.click(await screen.findByRole("button", { name: "Notifications" }));
    expect(await screen.findByText("How reminders and email are sent")).toBeInTheDocument();
    expect(screen.getByText(/while the reminder service runs/)).toBeInTheDocument();
    expect(screen.getByText("Safety alerts are always shown in the app.")).toBeInTheDocument();
  });

  it("rejects bad reminder hours and saves good ones", async () => {
    const user = userEvent.setup();
    const patches: Array<Record<string, unknown>> = [];
    const session = adminSession({
      ...common,
      "PATCH /admin/settings/notifications": (call) => {
        patches.push(call.body as Record<string, unknown>);
        return json(notificationSettings());
      },
    });
    const { container } = renderWithApp(<SettingsView />, session);
    await user.click(await screen.findByRole("button", { name: "Notifications" }));
    const hours = await screen.findByLabelText("Hours before an appointment");
    await expectNoA11yViolations(container);
    await user.clear(hours);
    await user.type(hours, "24, 0");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText(/Use whole numbers of hours from 1 to 168/)).toBeInTheDocument();
    await user.clear(hours);
    await user.type(hours, "1, 2, 3, 4");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Choose at most three reminders.")).toBeInTheDocument();
    expect(patches).toEqual([]);

    await user.clear(hours);
    await user.type(hours, "48, 4");
    await user.click(screen.getByRole("checkbox", { name: "Also send notifications by email" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({
      appointment_reminder_hours: [48, 4],
      email_enabled: true,
      reminders_enabled: true,
    });
  });

  it("validates the alert response time and sends whole minutes", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      ...common,
      "PATCH /admin/settings/safety": (call) => {
        patches.push(call.body);
        return json(safetySettings());
      },
    });
    const { container } = renderWithApp(<SettingsView />, session);
    await user.click(await screen.findByRole("button", { name: "Safety" }));
    const minutes = await screen.findByLabelText(/Minutes a therapist has to acknowledge/);
    await expectNoA11yViolations(container);
    await user.clear(minutes);
    await user.type(minutes, "2");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]!);
    expect(screen.getByText("Use whole minutes from 5 to 1440.")).toBeInTheDocument();
    expect(patches).toEqual([]);
    await user.clear(minutes);
    await user.type(minutes, "30");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]!);
    await waitFor(() => expect(patches).toEqual([{ alert_ack_minutes: 30 }]));
  });

  it("lets an admin switch the companion off and set a daily allowance", async () => {
    const user = userEvent.setup();
    const patches: unknown[] = [];
    const session = adminSession({
      ...common,
      "PATCH /admin/settings/safety": (call) => {
        patches.push(call.body);
        return json(safetySettings());
      },
    });
    renderWithApp(<SettingsView />, session);
    await user.click(await screen.findByRole("button", { name: "Safety" }));
    expect(await screen.findByText(/never diagnoses/)).toBeInTheDocument();
    const daily = screen.getByLabelText(/Messages each student can send a day/);
    await user.click(screen.getByRole("checkbox", { name: "Let students use the companion" }));
    await user.clear(daily);
    await user.type(daily, "5");
    await user.click(screen.getByRole("button", { name: "Save companion settings" }));
    expect(screen.getByText("Use a whole number from 10 to 500.")).toBeInTheDocument();
    expect(patches).toEqual([]);
    await user.clear(daily);
    await user.type(daily, "40");
    await user.click(screen.getByRole("button", { name: "Save companion settings" }));
    await waitFor(() =>
      expect(patches).toEqual([{ companion_enabled: false, companion_daily_messages: 40 }]),
    );
  });

  it("shows shipped crisis contacts without edit or remove controls", async () => {
    const user = userEvent.setup();
    renderWithApp(<SettingsView />, adminSession(common));
    await user.click(await screen.findByRole("button", { name: "Safety" }));
    expect(await screen.findByText("National helpline")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edit\s*Campus counselling/ })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Edit\s*National helpline/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Remove\s*National helpline/ }),
    ).not.toBeInTheDocument();
  });

  it("adds a crisis contact only with a way to reach it", async () => {
    const user = userEvent.setup();
    const posts: unknown[] = [];
    const session = adminSession({
      ...common,
      "POST /admin/settings/crisis-contacts": (call) => {
        posts.push(call.body);
        return json(contact(), 201);
      },
    });
    renderWithApp(<SettingsView />, session);
    await user.click(await screen.findByRole("button", { name: "Safety" }));
    await user.click(await screen.findByRole("button", { name: "Add contact" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a contact" });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByText("Enter a name.")).toBeInTheDocument();
    expect(
      within(dialog).getByText("Add a phone number, a link or a short description."),
    ).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Name"), "Night line");
    await user.type(within(dialog).getByLabelText("Phone"), "0000 111 222");
    await user.selectOptions(within(dialog).getByLabelText("Kind"), "helpline");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      label: "Night line",
      phone: "0000 111 222",
      kind: "helpline",
    });
  });

  it("explains why the last emergency contact can't be removed", async () => {
    const user = userEvent.setup();
    const session = adminSession({
      ...common,
      [`DELETE /admin/settings/crisis-contacts/${CONTACT}`]: () =>
        problem(409, "At least one emergency contact must stay active."),
    });
    renderWithApp(<SettingsView />, session);
    await user.click(await screen.findByRole("button", { name: "Safety" }));
    await user.click(await screen.findByRole("button", { name: /Remove\s*Campus counselling/ }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("That contact can't be removed")).toBeInTheDocument();
    expect(
      await screen.findAllByText("At least one emergency contact must stay active."),
    ).not.toHaveLength(0);
  });
});
