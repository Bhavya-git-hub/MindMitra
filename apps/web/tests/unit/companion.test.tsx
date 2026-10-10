import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CompanionChatView, CompanionHomeView } from "@/components/student/companion-views";
import type {
  CompanionConversation,
  CompanionMessage,
  CompanionStatus,
  CompanionSupport,
} from "@/lib/api/companion-schemas";

import { expectNoA11yViolations } from "../helpers/a11y";
import { navigation } from "../helpers/navigation";
import { json, problem, renderWithApp } from "../helpers/render";
import { contact, studentSession } from "../helpers/student-data";

const CONV = "0192a000-0000-7000-8000-0000000000c1";
const DISCLAIMER =
  "I'm an AI wellness companion, not a therapist. I can't diagnose or give medical advice, and I can make mistakes. If you're in danger, use Get help now.";

const status = (extra: Partial<CompanionStatus> = {}): CompanionStatus => ({
  available: true,
  reason: null,
  daily_limit: 100,
  remaining_today: 97,
  keeps_history: false,
  retention_hours: 24,
  disclaimer: DISCLAIMER,
  ...extra,
});

const conv = (extra: Partial<CompanionConversation> = {}): CompanionConversation => ({
  id: CONV,
  status: "active",
  started_at: "2026-10-10T09:00:00Z",
  last_message_at: "2026-10-10T09:01:00Z",
  expires_at: "2026-10-11T09:01:00Z",
  ...extra,
});

let seq = 0;
const msg = (extra: Partial<CompanionMessage> = {}): CompanionMessage => {
  seq += 1;
  return {
    id: `m-${seq}`,
    seq,
    role: "assistant",
    kind: "reply",
    content: "That sounds like a lot to carry.",
    show_support: false,
    created_at: "2026-10-10T09:01:00Z",
    ...extra,
  };
};

const crisisSupport = (extra: Partial<CompanionSupport> = {}): CompanionSupport => ({
  level: "crisis",
  escalated: true,
  care_team_notified: false,
  about_someone_else: false,
  contacts: [contact()],
  ...extra,
});

describe("companion home", () => {
  it("says what the companion is and isn't before a student starts, then opens a conversation", async () => {
    const user = userEvent.setup();
    const session = studentSession({
      "GET /companion/status": () => json(status()),
      "GET /companion/conversations": () => json([conv()]),
      "POST /companion/conversations": () => json(conv(), 201),
    });
    const { container } = renderWithApp(<CompanionHomeView />, session);

    expect(await screen.findByText(/not a therapist/)).toBeInTheDocument();
    expect(screen.getByText(/can't diagnose/)).toBeInTheDocument();
    expect(screen.getByText(/deleted a day after your last message/)).toBeInTheDocument();
    expect(screen.getByText("97 of 100 messages left today")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Get help now" })[0]).toHaveAttribute(
      "href",
      "/student/emergency",
    );
    expect(await screen.findByText("Open")).toBeInTheDocument();
    await expectNoA11yViolations(container);

    await user.click(screen.getByRole("button", { name: "Start a conversation" }));
    await waitFor(() =>
      expect(navigation.router.push).toHaveBeenCalledWith(`/student/assistant/${CONV}`),
    );
  });

  it("says plainly when the institution has switched it off", async () => {
    renderWithApp(
      <CompanionHomeView />,
      studentSession({
        "GET /companion/status": () => json(status({ available: false, reason: "switched_off" })),
        "GET /companion/conversations": () => json([]),
      }),
    );
    expect(await screen.findByText("The companion is off")).toBeInTheDocument();
    expect(screen.getByText(/switched the companion off/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start a conversation" })).not.toBeInTheDocument();
  });
});

describe("companion conversation", () => {
  function setup(
    reply: (body: unknown) => Response,
    messages: CompanionMessage[] = [],
    extra: Parameters<typeof studentSession>[0] = {},
  ) {
    const stored = [...messages];
    const session = studentSession({
      "GET /companion/status": () => json(status()),
      [`GET /companion/conversations/${CONV}`]: () =>
        json({ conversation: conv(), messages: stored }),
      [`POST /companion/conversations/${CONV}/messages`]: ({ body }) => {
        const content = (body as { content: string }).content;
        stored.push(msg({ role: "user", kind: null, content }));
        const r = reply(body);
        if (!r.ok) stored.pop();
        return r;
      },
      ...extra,
    });
    const view = renderWithApp(<CompanionChatView conversationId={CONV} />, session);
    return { ...view, stored };
  }

  it("sends a message and shows the reply, with the disclaimer always on screen", async () => {
    const user = userEvent.setup();
    let sent: unknown;
    const { container, stored } = setup((body) => {
      sent = body;
      const reply = msg({ content: "Exams can feel huge. What's weighing on you most?" });
      stored.push(reply);
      return json(
        {
          conversation: conv(),
          message: msg({ role: "user" }),
          reply,
          support: null,
          disclaimer: DISCLAIMER,
        },
        201,
      );
    });

    expect(await screen.findByRole("note")).toHaveTextContent(/not a therapist/);
    await user.type(screen.getByLabelText("Your message"), "  I'm stressed about exams  ");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(sent).toEqual({ content: "I'm stressed about exams" });
    const log = await screen.findByRole("log", { name: "Messages" });
    expect(await within(log).findByText(/What's weighing on you most/)).toBeInTheDocument();
    expect(screen.getByLabelText("Your message")).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await expectNoA11yViolations(container);
  });

  it("shows crisis contacts and says a person was told, without waiting for the AI", async () => {
    const user = userEvent.setup();
    const { container } = setup(() =>
      json(
        {
          conversation: conv({ status: "crisis_handoff" }),
          message: msg({ role: "user" }),
          reply: msg({ kind: "crisis", show_support: true, content: "Please reach out now." }),
          support: crisisSupport(),
          disclaimer: DISCLAIMER,
        },
        201,
      ),
    );
    await user.type(await screen.findByLabelText("Your message"), "I don't want to be here");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const panel = await screen.findByRole("alert", { name: "Please talk to a person now" });
    expect(within(panel).getByText("Please talk to a person now")).toBeInTheDocument();
    expect(within(panel).getByText("Demo helpline")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /Call/ })).toHaveAttribute(
      "href",
      "tel:+9101155500100",
    );
    expect(within(panel).getByRole("link", { name: "Get help now" })).toHaveAttribute(
      "href",
      "/student/emergency",
    );
    await expectNoA11yViolations(container);
  });

  it("brings the contacts back when a conversation that offered them is reopened", async () => {
    setup(
      () => json({}),
      [
        msg({ role: "user", kind: null, content: "..." }),
        msg({ kind: "crisis", show_support: true }),
      ],
      { "GET /me/safety/resources": () => json([contact({ label: "Campus counselling" })]) },
    );
    const panel = await screen.findByRole("alert", { name: "Please talk to a person now" });
    expect(await within(panel).findByText("Campus counselling")).toBeInTheDocument();
  });

  it("offers gentle support without an alarm when the reply only suggests it", async () => {
    setup(() => json({}), [msg({ kind: "reply", show_support: true })], {
      "GET /me/safety/resources": () => json([contact()]),
    });
    const panel = await screen.findByRole("status", { name: "Support is here if you need it" });
    expect(within(panel).getByText("Support is here if you need it")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the message and points to a person when the daily limit is reached", async () => {
    const user = userEvent.setup();
    setup(() =>
      problem(
        429,
        "You've reached today's message limit for the companion.",
        {},
        {
          "Retry-After": "3600",
        },
      ),
    );
    await user.type(await screen.findByLabelText("Your message"), "one more thing");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/today's message limit.*Get help now/)).toBeInTheDocument();
    expect(screen.getByLabelText("Your message")).toHaveValue("one more thing");
  });

  it("says so when the companion can't be reached", async () => {
    const user = userEvent.setup();
    setup(() => problem(503, "The companion isn't available right now."));
    await user.type(await screen.findByLabelText("Your message"), "hello");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("The companion isn't available right now.")).toBeInTheDocument();
  });

  it("deletes the conversation only after the student confirms", async () => {
    const user = userEvent.setup();
    let deleted = 0;
    setup(() => json({}), [], {
      [`DELETE /companion/conversations/${CONV}`]: () => {
        deleted += 1;
        return new Response(null, { status: 204 });
      },
    });
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(deleted).toBe(0);
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toBe(1));
    expect(navigation.router.push).toHaveBeenCalledWith("/student/assistant");
  });
});
