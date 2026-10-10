/**
 * Turns "I went to bed at 23:30 and woke at 07:00" into two exact instants.
 *
 * The wake time is the most recent time the clock has shown that value (this morning, or
 * yesterday morning if it hasn't happened yet today), and bedtime is the latest earlier time
 * matching its value. Everything is in the viewer's local time zone and sent as ISO instants.
 */

export interface SleepWindow {
  bedtime: string;
  wake_time: string;
  durationMinutes: number;
}

const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;

export function parseClock(value: string): { h: number; m: number } | null {
  const match = TIME.exec(value);
  return match ? { h: Number(match[1]), m: Number(match[2]) } : null;
}

export function sleepWindow(bed: string, wake: string, now: Date = new Date()): SleepWindow | null {
  const b = parseClock(bed);
  const w = parseClock(wake);
  if (!b || !w) return null;

  const wakeAt = new Date(now);
  wakeAt.setHours(w.h, w.m, 0, 0);
  if (wakeAt.getTime() > now.getTime()) wakeAt.setDate(wakeAt.getDate() - 1);

  const bedAt = new Date(wakeAt);
  bedAt.setHours(b.h, b.m, 0, 0);
  if (bedAt.getTime() >= wakeAt.getTime()) bedAt.setDate(bedAt.getDate() - 1);

  const durationMinutes = Math.round((wakeAt.getTime() - bedAt.getTime()) / 60_000);
  return { bedtime: bedAt.toISOString(), wake_time: wakeAt.toISOString(), durationMinutes };
}
