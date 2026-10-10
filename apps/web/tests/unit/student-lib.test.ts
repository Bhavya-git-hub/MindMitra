import { describe, expect, it } from "vitest";

import { createApiClient } from "@/lib/api/client";
import { createStudentApi } from "@/lib/api/student-api";
import { formatDuration, formatShortDate, modeLabel, relativeDay, titleCase } from "@/lib/format";
import { parseClock, sleepWindow } from "@/lib/sleep";
import { averageOf, chartRows, hasAny } from "@/lib/trend-data";
import { isUuid } from "@/lib/validation";

import { API, fakeApi, json, problem } from "../helpers/api";
import { dashboard, trendPoint } from "../helpers/student-data";

describe("sleepWindow", () => {
  const now = new Date(2026, 9, 10, 9, 0); // 10 Oct 2026, 09:00 local

  it("reads 23:30 to 07:00 as last night", () => {
    const w = sleepWindow("23:30", "07:00", now);
    expect(w?.durationMinutes).toBe(450);
    const bed = new Date(w!.bedtime);
    const wake = new Date(w!.wake_time);
    expect([bed.getDate(), bed.getHours(), bed.getMinutes()]).toEqual([9, 23, 30]);
    expect([wake.getDate(), wake.getHours()]).toEqual([10, 7]);
  });

  it("handles going to bed after midnight", () => {
    expect(sleepWindow("01:15", "08:00", now)?.durationMinutes).toBe(405);
  });

  it("uses yesterday morning when the wake time hasn't happened yet today", () => {
    const early = new Date(2026, 9, 10, 5, 0);
    const w = sleepWindow("23:00", "07:00", early)!;
    expect(new Date(w.wake_time).getDate()).toBe(9);
    expect(w.durationMinutes).toBe(480);
  });

  it("never produces a wake time in the future", () => {
    for (const hour of [0, 6, 7, 12, 23]) {
      const at = new Date(2026, 9, 10, hour, 30);
      const w = sleepWindow("22:00", "07:00", at)!;
      expect(new Date(w.wake_time).getTime()).toBeLessThanOrEqual(at.getTime());
    }
  });

  it("rejects values that are not a clock time", () => {
    expect(parseClock("24:00")).toBeNull();
    expect(parseClock("7:00")).toBeNull();
    expect(sleepWindow("", "07:00", now)).toBeNull();
  });
});

describe("format helpers", () => {
  it("formats durations", () => {
    expect(formatDuration(45)).toBe("45 min");
    expect(formatDuration(120)).toBe("2 h");
    expect(formatDuration(450)).toBe("7 h 30 min");
  });

  it("formats calendar dates without drifting across time zones", () => {
    expect(formatShortDate("2026-10-10", "Pacific/Auckland")).toBe(
      formatShortDate("2026-10-10", "America/Los_Angeles"),
    );
  });

  it("describes how long ago something was", () => {
    const now = new Date("2026-10-10T12:00:00Z");
    expect(relativeDay("2026-10-10T08:00:00Z", now)).toBe("today");
    expect(relativeDay("2026-10-09T08:00:00Z", now)).toBe("yesterday");
    expect(relativeDay("2026-10-05T08:00:00Z", now)).toBe("5 days ago");
  });

  it("tidies labels", () => {
    expect(titleCase("no_show")).toBe("No show");
    expect(modeLabel("in_person")).toBe("In person");
    expect(modeLabel("hybrid")).toBe("Hybrid");
  });
});

describe("trend data", () => {
  const points = [
    trendPoint(-2, { mood: 2, sleep_minutes: 360 }),
    trendPoint(-1),
    trendPoint(0, { mood: 4, sleep_minutes: 480 }),
  ];

  it("leaves days with nothing logged out of the series instead of drawing zero", () => {
    const rows = chartRows(points, ["mood"]);
    expect(rows).toHaveLength(3);
    expect("mood" in rows[1]!).toBe(false);
    expect(rows[2]!.mood).toBe(4);
  });

  it("converts sleep to hours", () => {
    expect(chartRows(points, ["sleep_hours"])[0]!.sleep_hours).toBe(6);
  });

  it("averages only the days that have data", () => {
    expect(averageOf(points, "mood")).toBe(3);
    expect(averageOf(points, "stress")).toBeNull();
    expect(hasAny(points, "mood")).toBe(true);
    expect(hasAny(points, "energy")).toBe(false);
  });
});

describe("isUuid", () => {
  it("only lets well-formed ids into API paths", () => {
    expect(isUuid("0192a000-0000-7000-8000-000000000001")).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("../me")).toBe(false);
    expect(isUuid("0192a000-0000-7000-8000-000000000001/x")).toBe(false);
  });
});

describe("student API client", () => {
  function setup(handlers: Parameters<typeof fakeApi>[0]) {
    const fake = fakeApi(handlers);
    const client = createApiClient({
      baseUrl: () => API,
      fetchImpl: fake.fetch,
      hooks: { getAccessToken: () => "access-1", onUnauthorized: async () => false },
    });
    return { fake, api: createStudentApi(client, () => "Asia/Kolkata") };
  }

  it("sends the student's time zone so 'today' means their today", async () => {
    const { fake, api } = setup({ "GET /me/dashboard": () => json(dashboard()) });
    await api.dashboard();
    expect(fake.calls[0]!.query.get("tz")).toBe("Asia/Kolkata");
  });

  it("asks for the requested number of days", async () => {
    const { fake, api } = setup({
      "GET /me/wellness/trends": () => json({ days: 90, points: [], disclaimer: "x" }),
    });
    await api.trends(90);
    expect(fake.calls[0]!.query.get("days")).toBe("90");
  });

  it("leaves empty filters out of the query", async () => {
    const { fake, api } = setup({ "GET /therapists": () => json([]) });
    await api.therapists({ specialty: "", language: undefined, acceptingOnly: false });
    expect(fake.calls[0]!.query.toString()).toBe("");
  });

  it("refuses a response that doesn't match the contract", async () => {
    const { api } = setup({ "GET /me/dashboard": () => json({ unexpected: true }) });
    await expect(api.dashboard()).rejects.toBeTruthy();
  });

  it("surfaces problem details from the API", async () => {
    const { api } = setup({
      "POST /me/appointments": () => problem(409, "You already have 3 upcoming appointments."),
    });
    await expect(api.bookAppointment("a")).rejects.toMatchObject({ status: 409 });
  });
});
