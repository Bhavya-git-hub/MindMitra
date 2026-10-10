import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NotificationBell, notificationHref } from "@/components/layout/notification-bell";
import { ConversationView } from "@/components/student/messages-views";
import { AppointmentsView } from "@/components/student/care-views";
import { AppointmentsView as TherapistAppointmentsView } from "@/components/therapist/appointments-view";
import type { AppNotification } from "@/lib/api/notification-schemas";
import { parseEvent } from "@/lib/realtime/events";
import {
  CLOSE_ORIGIN,
  CLOSE_UNAUTHENTICATED,
  RealtimeClient,
  reconnectDelay,
  type SocketLike,
} from "@/lib/realtime/realtime-client";
import { RealtimeProvider, realtimeUrl, useRealtimeEvent } from "@/lib/realtime/realtime-provider";

import { expectNoA11yViolations } from "../helpers/a11y";
import { json, problem, renderWithApp, type TestSession } from "../helpers/render";
import {
  THERAPIST_ID,
  appointment,
  conversation,
  message,
  slot,
  studentSession,
} from "../helpers/student-data";
import {
  APPOINTMENT_ID,
  appointment as therapistAppointment,
  profile,
  therapistSession,
} from "../helpers/therapist-data";

// ---- a fake WebSocket ------------------------------------------------------------------------

class FakeSocket implements SocketLike {
  sent: unknown[] = [];
  closedWith: number | null = null;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(readonly url: string) {}

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close(code = 1000) {
    this.closedWith = code;
  }
  open() {
    this.onopen?.(new Event("open"));
  }
  receive(frame: unknown) {
    this.onmessage?.(
      new MessageEvent("message", {
        data: typeof frame === "string" ? frame : JSON.stringify(frame),
      }),
    );
  }
  drop(code: number) {
    this.onclose?.({ code } as CloseEvent);
  }
}

function socketFactory() {
  const sockets: FakeSocket[] = [];
  const create = (url: string) => {
    const s = new FakeSocket(url);
    sockets.push(s);
    return s;
  };
  return { sockets, create };
}

/** Renders `ui` inside a live connection, and returns a helper that opens it. */
function renderLive(ui: React.ReactElement, session: TestSession) {
  const { sockets, create } = socketFactory();
  const result = renderWithApp(
    <RealtimeProvider createSocket={create} url="ws://api.test/api/v1/ws">
      {ui}
    </RealtimeProvider>,
    session,
  );
  async function connect(): Promise<FakeSocket> {
    await waitFor(() => expect(sockets.length).toBeGreaterThan(0));
    const s = sockets[sockets.length - 1]!;
    act(() => {
      s.open();
      s.receive({ type: "ready" });
    });
    return s;
  }
  return { ...result, sockets, connect };
}

// ---- the real-time client ----------------------------------------------------------------------

describe("real-time client", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  function client(overrides: Partial<ConstructorParameters<typeof RealtimeClient>[0]> = {}) {
    const { sockets, create } = socketFactory();
    const refresh = vi.fn(async () => true);
    let token = "access-1";
    const c = new RealtimeClient({
      url: "ws://api.test/api/v1/ws",
      getToken: () => token,
      refresh,
      createSocket: create,
      random: () => 0.5,
      ...overrides,
    });
    const events: unknown[] = [];
    c.subscribe((e) => events.push(e));
    return {
      c,
      sockets,
      refresh,
      events,
      setToken: (t: string) => {
        token = t;
      },
    };
  }

  it("builds the socket URL from the API origin, with no token in it", () => {
    expect(realtimeUrl("https://api.example.org")).toBe("wss://api.example.org/api/v1/ws");
    expect(realtimeUrl("http://localhost:8000")).toBe("ws://localhost:8000/api/v1/ws");
  });

  it("sends the token in the first frame and passes on known events only", () => {
    const { c, sockets, events } = client();
    c.start();
    const s = sockets[0]!;
    expect(s.url).not.toContain("access");
    s.open();
    expect(s.sent).toEqual([{ type: "auth", token: "access-1" }]);
    s.receive({ type: "ready" });
    expect(c.getStatus()).toBe("open");
    s.receive({ type: "message", with: "u2", message_id: "m1" });
    s.receive({ type: "pong" });
    s.receive({ type: "something_new", secret: "x" });
    s.receive("not json");
    expect(events).toEqual([{ type: "message", with: "u2", message_id: "m1" }]);
    vi.advanceTimersByTime(25_000);
    expect(s.sent).toContainEqual({ type: "ping" });
    c.stop();
    expect(s.closedWith).toBe(1000);
  });

  it("reconnects with backoff and asks views to refresh once it is back", () => {
    const { c, sockets, events } = client();
    c.start();
    sockets[0]!.open();
    sockets[0]!.receive({ type: "ready" });
    sockets[0]!.drop(1006);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(reconnectDelay(0, () => 0.5));
    expect(sockets).toHaveLength(2);
    sockets[1]!.open();
    sockets[1]!.receive({ type: "ready" });
    expect(events).toEqual([{ type: "resync" }]);
  });

  it("keeps backing off, up to a cap", () => {
    expect(reconnectDelay(0, () => 0)).toBe(500);
    expect(reconnectDelay(3, () => 1)).toBe(8_000);
    expect(reconnectDelay(20, () => 1)).toBe(30_000);
  });

  it("refreshes the session once when the token is refused, then reconnects", async () => {
    const { c, sockets, refresh, setToken } = client();
    c.start();
    sockets[0]!.open();
    setToken("access-2");
    sockets[0]!.drop(CLOSE_UNAUTHENTICATED);
    await vi.waitFor(() => expect(sockets).toHaveLength(2));
    expect(refresh).toHaveBeenCalledTimes(1);
    sockets[1]!.open();
    expect(sockets[1]!.sent).toEqual([{ type: "auth", token: "access-2" }]);
  });

  it("stops when the session is over or the origin is refused", async () => {
    const ended = client({ refresh: vi.fn(async () => false) });
    ended.c.start();
    ended.sockets[0]!.drop(CLOSE_UNAUTHENTICATED);
    await vi.waitFor(() => expect(ended.c.getStatus()).toBe("stopped"));
    vi.advanceTimersByTime(60_000);
    expect(ended.sockets).toHaveLength(1);

    const refused = client();
    refused.c.start();
    refused.sockets[0]!.drop(CLOSE_ORIGIN);
    vi.advanceTimersByTime(60_000);
    expect(refused.c.getStatus()).toBe("stopped");
    expect(refused.sockets).toHaveLength(1);
  });

  it("waits for a token before connecting", () => {
    let token: string | null = null;
    const { c, sockets } = client({ getToken: () => token });
    c.start();
    expect(sockets).toHaveLength(0);
    token = "access-1";
    vi.advanceTimersByTime(1_000);
    expect(sockets).toHaveLength(1);
  });

  it("validates event shapes", () => {
    expect(parseEvent({ type: "appointment", appointment_id: "a", event: "confirmed" })).toEqual({
      type: "appointment",
      appointment_id: "a",
      event: "confirmed",
    });
    expect(parseEvent({ type: "message" })).toBeNull();
    expect(parseEvent({ type: "resync" })).toBeNull(); // only the client makes these
  });
});

describe("real-time provider", () => {
  function Listener({ seen }: { seen: unknown[] }) {
    useRealtimeEvent((e) => seen.push(e));
    return null;
  }

  it("connects once signed in and hands events to listening views", async () => {
    const seen: unknown[] = [];
    const { connect } = renderLive(<Listener seen={seen} />, studentSession());
    const s = await connect();
    expect(s.sent[0]).toEqual({ type: "auth", token: "access-2" });
    act(() => s.receive({ type: "notifications_read" }));
    expect(seen).toEqual([{ type: "notifications_read" }]);
  });

  it("asks views to refresh when the tab comes back into view", async () => {
    const seen: unknown[] = [];
    const { connect } = renderLive(<Listener seen={seen} />, studentSession());
    await connect();
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(seen).toEqual([{ type: "resync" }]);
  });

  it("does nothing outside a provider", () => {
    const seen: unknown[] = [];
    renderWithApp(<Listener seen={seen} />, studentSession());
    expect(seen).toEqual([]);
  });
});

// ---- notifications ----------------------------------------------------------------------------

const note = (extra: Partial<AppNotification> = {}): AppNotification => ({
  id: "n1",
  type: "new_message",
  priority: "normal",
  title: "You have a new message",
  payload: { message_id: "m1" },
  created_at: "2026-10-09T10:00:00Z",
  read_at: null,
  ...extra,
});

describe("notification bell", () => {
  it("links each kind of notification to the right page for the reader's role", () => {
    expect(notificationHref(note(), "student")).toBe("/student/messages");
    expect(notificationHref(note(), "therapist")).toBe("/therapist/messages");
    expect(notificationHref(note(), "administrator")).toBeNull();
    const reminder = note({ type: "appointment_reminder", payload: { event: "reminder" } });
    expect(notificationHref(reminder, "therapist")).toBe("/therapist/appointments");
    expect(notificationHref(note({ type: "risk_alert" }), "therapist")).toBe("/therapist/alerts");
    expect(notificationHref(note({ type: "risk_alert" }), "student")).toBeNull();
    const request = note({ type: "system", payload: { request_id: "r1" } });
    expect(notificationHref(request, "teacher")).toBe("/teacher/support-requests");
    expect(notificationHref(note({ type: "system", payload: {} }), "student")).toBeNull();
  });

  it("shows the unread count, lists notifications and marks them read", async () => {
    let unread = 2;
    const session = studentSession({
      "GET /me/notifications/unread-count": () => json({ unread }),
      "GET /me/notifications": () =>
        json({
          items: [
            note(),
            note({
              id: "n2",
              type: "appointment_update",
              title: "Your appointment was confirmed",
              payload: { appointment_id: "a1", event: "confirmed" },
              read_at: "2026-10-09T09:00:00Z",
            }),
          ],
          unread,
        }),
      "POST /me/notifications/read-all": () => {
        unread = 0;
        return json({ marked_read: 2 });
      },
      "POST /me/notifications/n1/read": () => new Response(null, { status: 204 }),
    });
    const { container } = renderWithApp(<NotificationBell role="student" />, session);
    const user = userEvent.setup();
    const bell = await screen.findByRole("button", { name: "Open notifications, 2 unread" });
    await expectNoA11yViolations(container);
    await user.click(bell);
    const panel = await screen.findByRole("dialog", { name: "Notifications" });
    const list = await within(panel).findByRole("list", { name: "Notifications" });
    const links = within(list).getAllByRole("link");
    expect(links[0]).toHaveAttribute("href", "/student/messages");
    expect(links[0]).toHaveTextContent("You have a new message (unread)");
    expect(links[1]).toHaveAttribute("href", "/student/appointments");
    await expectNoA11yViolations(document.body);

    await user.click(within(panel).getByRole("button", { name: "Mark all as read" }));
    expect(await within(panel).findByText(/all caught up/)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Mark all as read" })).toBeDisabled();
  });

  it("updates the count when a notification arrives live", async () => {
    let unread = 0;
    const { connect } = renderLive(
      <NotificationBell role="therapist" />,
      therapistSession({
        "GET /me/notifications/unread-count": () => json({ unread }),
      }),
    );
    expect(await screen.findByRole("button", { name: "Open notifications" })).toBeInTheDocument();
    const s = await connect();
    unread = 1;
    act(() =>
      s.receive({
        type: "notification",
        id: "n9",
        notification_type: "new_message",
        title: "You have a new message",
      }),
    );
    expect(
      await screen.findByRole("button", { name: "Open notifications, 1 unread" }),
    ).toBeInTheDocument();
  });
});

// ---- the student's appointments -----------------------------------------------------------------

describe("student appointments: moving, cancelling, session status", () => {
  const upcoming = appointment({ id: "a-up", status: "confirmed" });

  it("moves an appointment to another open time with the same therapist", async () => {
    let moved = false;
    const session = studentSession({
      "GET /me/appointments": () =>
        json([moved ? { ...upcoming, status: "requested", reschedule_count: 1 } : upcoming]),
      [`GET /therapists/${THERAPIST_ID}/slots`]: () =>
        json([
          slot({ id: "s1", starts_at: "2030-01-07T09:00:00Z", ends_at: "2030-01-07T09:50:00Z" }),
          slot({ id: "s2", starts_at: "2030-01-08T15:00:00Z", ends_at: "2030-01-08T15:50:00Z" }),
        ]),
      "POST /me/appointments/a-up/reschedule": ({ body }) => {
        moved = true;
        expect(body).toEqual({ availability_id: "s2" });
        return json({ ...upcoming, status: "requested", reschedule_count: 1 });
      },
    });
    renderWithApp(<AppointmentsView />, session);
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Move" }))[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Move this appointment" });
    expect(dialog).toHaveTextContent("Dr. Priya Nair will confirm the new time");
    const submit = within(dialog).getByRole("button", { name: "Move appointment" });
    expect(submit).toBeDisabled();
    const radios = await within(dialog).findAllByRole("radio");
    expect(radios).toHaveLength(2);
    await expectNoA11yViolations(document.body);
    await user.click(radios[1]!);
    await user.click(submit);
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Move this appointment" })).toBeNull(),
    );
    expect(session.api.calls.some((c) => c.path === "/me/appointments/a-up/reschedule")).toBe(true);
    expect((await screen.findAllByText("Waiting for confirmation")).length).toBeGreaterThan(0);
  });

  it("keeps the dialog open with a clear message when the time was just taken", async () => {
    renderWithApp(
      <AppointmentsView />,
      studentSession({
        "GET /me/appointments": () => json([upcoming]),
        [`GET /therapists/${THERAPIST_ID}/slots`]: () =>
          json([slot({ id: "s1", starts_at: "2030-01-07T09:00:00Z" })]),
        "POST /me/appointments/a-up/reschedule": () =>
          problem(409, "Sorry, that time has just been taken. Please choose another."),
      }),
    );
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Move" }))[0]!);
    const dialog = await screen.findByRole("dialog", { name: "Move this appointment" });
    await user.click(await within(dialog).findByRole("radio"));
    await user.click(within(dialog).getByRole("button", { name: "Move appointment" }));
    expect(await within(dialog).findByText(/just been taken/)).toBeInTheDocument();
  });

  it("says when there is nowhere to move to, and hides Move once the limit is reached", async () => {
    renderWithApp(
      <AppointmentsView />,
      studentSession({
        "GET /me/appointments": ({ query }) =>
          json(
            query.get("upcoming") === "true"
              ? [
                  upcoming,
                  appointment({
                    id: "a-max",
                    can_reschedule: false,
                    reschedule_count: 3,
                    rescheduled_at: "2026-10-09T10:00:00Z",
                  }),
                ]
              : [],
          ),
        [`GET /therapists/${THERAPIST_ID}/slots`]: () => json([]),
      }),
    );
    const user = userEvent.setup();
    expect(await screen.findAllByRole("button", { name: "Move" })).toHaveLength(1);
    expect(screen.getByText(/Moved 3 times/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Move" }));
    expect(await screen.findByText("There are no other open times right now.")).toBeInTheDocument();
  });

  it("cancels with an optional reason from a fixed list", async () => {
    const session = studentSession({
      "GET /me/appointments": () => json([upcoming]),
      "PATCH /me/appointments/a-up": () => json({ ...upcoming, status: "cancelled" }),
    });
    renderWithApp(<AppointmentsView />, session);
    const user = userEvent.setup();
    await user.click((await screen.findAllByRole("button", { name: "Cancel" }))[0]!);
    const dialog = await screen.findByRole("alertdialog");
    const select = within(dialog).getByLabelText("Reason (optional)");
    expect(
      within(select).queryByRole("option", { name: "The therapist isn't available" }),
    ).toBeNull();
    await user.selectOptions(select, "feeling_better");
    await expectNoA11yViolations(document.body);
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));
    await waitFor(() =>
      expect(session.api.calls.find((c) => c.method === "PATCH")?.body).toEqual({
        status: "cancelled",
        reason: "feeling_better",
      }),
    );
  });

  it("shows a cancellation reason and a session in progress", async () => {
    renderWithApp(
      <AppointmentsView />,
      studentSession({
        "GET /me/appointments": ({ query }) =>
          json(
            query.get("upcoming") === "true"
              ? [appointment({ id: "a-live", session_status: "in_progress" })]
              : [
                  appointment({
                    id: "a-c",
                    status: "cancelled",
                    can_cancel: false,
                    can_reschedule: false,
                    cancel_reason: "therapist_unavailable",
                  }),
                ],
          ),
      }),
    );
    expect(await screen.findByText(/Your therapist has started this session/)).toBeInTheDocument();
    expect(await screen.findByText("Reason: The therapist isn't available")).toBeInTheDocument();
  });

  it("refreshes when the therapist changes an appointment", async () => {
    let status = "requested";
    const { connect } = renderLive(
      <AppointmentsView />,
      studentSession({
        "GET /me/appointments": () => json([appointment({ id: "a-up", status })]),
      }),
    );
    expect((await screen.findAllByText("Waiting for confirmation")).length).toBeGreaterThan(0);
    const s = await connect();
    status = "confirmed";
    act(() => s.receive({ type: "appointment", appointment_id: "a-up", event: "confirmed" }));
    expect((await screen.findAllByText("Confirmed")).length).toBeGreaterThan(0);
  });
});

// ---- the therapist's appointments ----------------------------------------------------------------

describe("therapist appointments: moving and cancelling", () => {
  const verified = { "GET /therapist/profile": () => json(profile()) };
  const confirmed = therapistAppointment({
    status: "confirmed",
    starts_at: "2030-01-06T10:00:00Z",
    ends_at: "2030-01-06T10:50:00Z",
  });

  it("moves an appointment to one of the therapist's own free times", async () => {
    const posted: unknown[] = [];
    renderWithApp(
      <TherapistAppointmentsView />,
      therapistSession({
        ...verified,
        "GET /therapist/appointments": () => json([confirmed]),
        "GET /therapist/availability": () =>
          json([
            {
              id: "own",
              starts_at: confirmed.starts_at,
              ends_at: confirmed.ends_at,
              mode: "video",
              booked: true,
              appointment_id: APPOINTMENT_ID,
              appointment_status: "confirmed",
            },
            {
              id: "taken",
              starts_at: "2030-01-07T10:00:00Z",
              ends_at: "2030-01-07T10:50:00Z",
              mode: "video",
              booked: true,
              appointment_id: "x",
              appointment_status: "requested",
            },
            {
              id: "free",
              starts_at: "2030-01-08T10:00:00Z",
              ends_at: "2030-01-08T10:50:00Z",
              mode: "in_person",
              booked: false,
              appointment_id: null,
              appointment_status: null,
            },
          ]),
        [`POST /therapist/appointments/${APPOINTMENT_ID}/reschedule`]: ({ body }) => {
          posted.push(body);
          return json({ ...confirmed, reschedule_count: 1 });
        },
      }),
    );
    const user = userEvent.setup();
    // Switch to the upcoming tab, where confirmed appointments are listed.
    await user.click(await screen.findByRole("button", { name: "Upcoming" }));
    await user.click(await screen.findByRole("button", { name: "Move" }));
    const dialog = await screen.findByRole("dialog", { name: "Move this appointment" });
    const radios = await within(dialog).findAllByRole("radio");
    expect(radios).toHaveLength(1); // only the free time
    await user.click(radios[0]!);
    await user.click(within(dialog).getByRole("button", { name: "Move appointment" }));
    await waitFor(() => expect(posted).toEqual([{ availability_id: "free" }]));
  });

  it("can give a reason when cancelling", async () => {
    const patches: unknown[] = [];
    renderWithApp(
      <TherapistAppointmentsView />,
      therapistSession({
        ...verified,
        "GET /therapist/appointments": () => json([confirmed]),
        [`PATCH /appointments/${APPOINTMENT_ID}`]: ({ body }) => {
          patches.push(body);
          return json({});
        },
      }),
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Upcoming" }));
    await user.click(await screen.findByRole("button", { name: "Cancel" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.selectOptions(
      within(dialog).getByLabelText("Reason (optional)"),
      "therapist_unavailable",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel appointment" }));
    await waitFor(() =>
      expect(patches).toEqual([{ status: "cancelled", cancel_reason: "therapist_unavailable" }]),
    );
  });
});

// ---- live messaging ------------------------------------------------------------------------------

describe("live messaging", () => {
  it("shows a new message from the other person without a refresh, and nothing for others", async () => {
    let rows = [message({ id: "m1", body: "Earlier" })];
    const session = studentSession({
      "GET /me/conversations": () => json([conversation()]),
      [`GET /me/conversations/${THERAPIST_ID}/messages`]: () => json(rows),
      [`POST /me/conversations/${THERAPIST_ID}/read`]: () => json({ marked_read: 1 }),
    });
    const { connect } = renderLive(<ConversationView otherId={THERAPIST_ID} />, session);
    await screen.findByText("Earlier");
    const s = await connect();
    const loads = () =>
      session.api.calls.filter((c) => c.method === "GET" && c.path.endsWith("/messages")).length;
    const before = loads();
    act(() => s.receive({ type: "message", with: "someone-else", message_id: "x" }));
    expect(loads()).toBe(before);

    rows = [
      ...rows,
      message({ id: "m2", body: "Just checking in", created_at: "2026-10-09T12:00:00Z" }),
    ];
    act(() => s.receive({ type: "message", with: THERAPIST_ID, message_id: "m2" }));
    expect(await screen.findByText("Just checking in")).toBeInTheDocument();
    const items = within(screen.getByRole("list", { name: "Messages" })).getAllByRole("listitem");
    expect(items.at(-1)).toHaveTextContent("Just checking in");
  });

  it("lets the student read an ended conversation but not reply", async () => {
    renderWithApp(
      <ConversationView otherId={THERAPIST_ID} />,
      studentSession({
        "GET /me/conversations": () => json([conversation({ active: false })]),
        [`GET /me/conversations/${THERAPIST_ID}/messages`]: () =>
          json([message({ id: "m1", body: "Take care" })]),
        [`POST /me/conversations/${THERAPIST_ID}/read`]: () => json({ marked_read: 0 }),
      }),
    );
    expect(await screen.findByText("Take care")).toBeInTheDocument();
    expect(await screen.findByText(/you can read it but not reply/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Write a message")).not.toBeInTheDocument();
  });
});
