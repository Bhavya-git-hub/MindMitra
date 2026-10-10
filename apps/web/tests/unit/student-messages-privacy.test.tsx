import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { EmergencyView, dialable } from "@/components/student/emergency-view";
import { ConversationView, MessagesView } from "@/components/student/messages-views";
import { ConsentView, PrivacyCenterView } from "@/components/student/privacy-views";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp } from "../helpers/render";
import {
  THERAPIST_ID,
  consent,
  contact,
  conversation,
  message,
  studentSession,
} from "../helpers/student-data";

describe("messages", () => {
  it("explains when messaging has not opened yet", async () => {
    renderWithApp(<MessagesView />, studentSession({ "GET /me/conversations": () => json([]) }));
    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
    expect(
      screen.getByText(/once a therapist has confirmed your first appointment/),
    ).toBeInTheDocument();
  });

  it("lists conversations with unread counts", async () => {
    const { container } = renderWithApp(
      <MessagesView />,
      studentSession({ "GET /me/conversations": () => json([conversation({ unread_count: 2 })]) }),
    );
    const link = await screen.findByRole("link", { name: /Dr\. Priya Nair/ });
    expect(link).toHaveAttribute("href", `/student/messages/${THERAPIST_ID}`);
    expect(within(link).getByText("2 new")).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});

describe("conversation", () => {
  function setup(extra: Parameters<typeof studentSession>[0] = {}) {
    const sent: unknown[] = [];
    const session = studentSession({
      "GET /me/conversations": () => json([conversation()]),
      [`GET /me/conversations/${THERAPIST_ID}/messages`]: () =>
        // Deliberately out of order: the view sorts oldest first itself.
        json([
          message({ id: "m2", body: "Latest", created_at: "2026-10-09T11:00:00Z" }),
          message({ id: "m1", body: "Earlier" }),
        ]),
      [`POST /me/conversations/${THERAPIST_ID}/read`]: () => json({ marked_read: 2 }),
      [`POST /me/conversations/${THERAPIST_ID}/messages`]: ({ body }) => {
        sent.push(body);
        return json(
          {
            message: message({ id: "m3", mine: true, body: (body as { body: string }).body }),
            support: null,
          },
          201,
        );
      },
      ...extra,
    });
    renderWithApp(<ConversationView otherId={THERAPIST_ID} />, session);
    return { session, sent };
  }

  it("shows messages oldest first and marks the therapist's unread ones as read", async () => {
    const { session } = setup();
    const list = await screen.findByRole("list", { name: "Messages" });
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([expect.stringContaining("Earlier"), expect.stringContaining("Latest")]);
    await waitFor(() =>
      expect(session.api.calls.some((c) => c.method === "POST" && c.path.endsWith("/read"))).toBe(
        true,
      ),
    );
  });

  it("sends a message with a client id and clears the box", async () => {
    const { sent } = setup();
    const user = userEvent.setup();
    const box = await screen.findByLabelText("Write a message");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(box, "Thank you");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(box).toHaveValue(""));
    expect(sent).toEqual([
      { body: "Thank you", client_msg_id: expect.stringMatching(/^[0-9a-f-]{36}$/) },
    ]);
  });

  it("retries with the same client id after a failure so nothing is sent twice", async () => {
    let attempts = 0;
    const ids: string[] = [];
    setup({
      [`POST /me/conversations/${THERAPIST_ID}/messages`]: ({ body }) => {
        attempts += 1;
        ids.push((body as { client_msg_id: string }).client_msg_id);
        return attempts === 1
          ? problem(503, "Down")
          : json({ message: message({ id: "m3", mine: true }), support: null }, 201);
      },
    });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Write a message"), "Hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/wasn't sent/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(attempts).toBe(2));
    expect(ids[0]).toBe(ids[1]);
  });

  it("shows support options when the API says the message may call for them", async () => {
    setup({
      [`POST /me/conversations/${THERAPIST_ID}/messages`]: () =>
        json(
          {
            message: message({ id: "m3", mine: true }),
            support: { message: "If it's too much, help is here.", help_path: "/help" },
          },
          201,
        ),
    });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Write a message"), "I can't cope");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If it's too much, help is here.");
  });

  it("is read-only once the care relationship has ended", async () => {
    setup({ "GET /me/conversations": () => json([conversation({ active: false })]) });
    expect(await screen.findByText(/This conversation has ended/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Write a message")).not.toBeInTheDocument();
  });
});

describe("privacy center", () => {
  it("lists who has viewed the student's data by role, never by name", async () => {
    const { container } = renderWithApp(
      <PrivacyCenterView />,
      studentSession({
        "GET /me/privacy/access-history": () =>
          json([
            {
              occurred_at: "2026-10-09T10:00:00Z",
              actor_role: "therapist",
              action: "mood.read",
              resource_type: "mood_entry",
            },
          ]),
      }),
    );
    expect(await screen.findByText(/A therapist on your care team/)).toBeInTheDocument();
    expect(screen.getByText(/Teachers and administrators never/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("says plainly when nobody has looked", async () => {
    renderWithApp(
      <PrivacyCenterView />,
      studentSession({ "GET /me/privacy/access-history": () => json([]) }),
    );
    expect(await screen.findByText("No one else has viewed your information.")).toBeInTheDocument();
  });

  it("downloads the export as a file", async () => {
    const created: Blob[] = [];
    URL.createObjectURL = (blob: Blob | MediaSource) => {
      created.push(blob as Blob);
      return "blob:test";
    };
    URL.revokeObjectURL = () => {};
    const session = studentSession({
      "GET /me/privacy/access-history": () => json([]),
      "GET /me/privacy/export": () => json({ mood_entries: [{ mood_score: 4 }] }),
    });
    renderWithApp(<PrivacyCenterView />, session);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Download my data" }));
    await waitFor(() => expect(created).toHaveLength(1));
    expect(JSON.parse(await created[0]!.text())).toEqual({ mood_entries: [{ mood_score: 4 }] });
  });
});

describe("consent management", () => {
  const required = consent({
    scope: "terms_and_privacy",
    title: "Terms and privacy notice",
    required: true,
    granted: true,
  });

  it("shows each choice as a switch, and the required one as fixed", async () => {
    const { container } = renderWithApp(
      <ConsentView />,
      studentSession({ "GET /me/consents": () => json([required, consent()]) }),
    );
    expect(await screen.findByText("Required")).toBeInTheDocument();
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    expect(screen.getByRole("switch", { name: /Share my mood check-ins/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    await expectNoA11yViolations(container);
  });

  it("turns sharing on and then off, saving each change immediately", async () => {
    let granted = false;
    const session = studentSession({
      "GET /me/consents": () => json([consent({ granted })]),
      "PUT /me/consents/share_mood_with_care_team": ({ body }) => {
        granted = (body as { granted: boolean }).granted;
        return json(consent({ granted, granted_at: granted ? "2026-10-10T08:00:00Z" : null }));
      },
    });
    renderWithApp(<ConsentView />, session);
    const user = userEvent.setup();
    const toggle = await screen.findByRole("switch", { name: /Share my mood check-ins/ });
    await user.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    await user.click(toggle);
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "false"));
    expect(session.api.calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([
      { granted: true },
      { granted: false },
    ]);
  });

  it("keeps the old state and explains if a change can't be saved", async () => {
    renderWithApp(
      <ConsentView />,
      studentSession({
        "GET /me/consents": () => json([consent()]),
        "PUT /me/consents/share_mood_with_care_team": () => problem(503, "Down"),
      }),
    );
    const toggle = await screen.findByRole("switch");
    await userEvent.setup().click(toggle);
    expect(await screen.findByText(/couldn't update that setting/i)).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });
});

describe("emergency support", () => {
  const contacts = [
    contact({ id: "e", kind: "emergency", label: "Emergency services", phone: "112", url: null }),
    contact(),
    contact({
      id: "c",
      kind: "campus",
      label: "Campus counselling",
      phone: null,
      url: "javascript:alert(1)",
    }),
  ];

  it("lists contacts from the API as dialable links, grouped by kind", async () => {
    const { container } = renderWithApp(
      <EmergencyView />,
      studentSession({ "GET /me/safety/resources": () => json(contacts) }),
    );
    expect(await screen.findByText("Emergency services")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Call 112/ })).toHaveAttribute("href", "tel:112");
    expect(screen.getByRole("link", { name: /Call \+91/ })).toHaveAttribute(
      "href",
      "tel:+9101155500100",
    );
    expect(screen.getByRole("heading", { name: "At your institution" })).toBeInTheDocument();
    expect(screen.getByText(/immediate danger/)).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("never turns an unsafe web address into a link", async () => {
    renderWithApp(
      <EmergencyView />,
      studentSession({ "GET /me/safety/resources": () => json(contacts) }),
    );
    await screen.findByText("Campus counselling");
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
  });

  it("sends a request for someone to reach out and says who will see it", async () => {
    const session = studentSession({
      "GET /me/safety/resources": () => json(contacts),
      "POST /me/support-requests": () =>
        json(
          {
            id: "r1",
            status: "open",
            already_open: false,
            reaches_care_team: true,
            created_at: "2026-10-10T08:00:00Z",
          },
          201,
        ),
    });
    renderWithApp(<EmergencyView />, session);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/Anything you'd like them to know/), "Hard week");
    await user.click(screen.getByRole("button", { name: "Ask someone to reach out" }));
    expect(await screen.findByText(/Your care team has been told/)).toBeInTheDocument();
    expect(session.api.calls.find((c) => c.path === "/me/support-requests")?.body).toEqual({
      message: "Hard week",
    });
  });

  it("does not claim a second request was sent when one is already open", async () => {
    renderWithApp(
      <EmergencyView />,
      studentSession({
        "GET /me/safety/resources": () => json([]),
        "POST /me/support-requests": () =>
          json(
            {
              id: "r1",
              status: "open",
              already_open: true,
              reaches_care_team: false,
              created_at: "2026-10-10T08:00:00Z",
            },
            201,
          ),
      }),
    );
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Ask someone to reach out" }));
    expect(await screen.findByText(/already have a request open/)).toBeInTheDocument();
  });

  it("still shows the emergency guidance and a way to reach out if the list can't load", async () => {
    renderWithApp(
      <EmergencyView />,
      studentSession({ "GET /me/safety/resources": () => problem(503, "Down") }),
    );
    expect(screen.getByText(/immediate danger/)).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask someone to reach out" })).toBeInTheDocument();
  });

  it("reduces a phone number to digits for dialling", () => {
    expect(dialable("+91 (0) 11 5550-0100")).toBe("+9101155500100");
  });
});
