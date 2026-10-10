/** Date, time and number formatting for the student portal (the viewer's locale and zone). */

const LOCALE = undefined; // the browser's own locale

export function formatDateTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(LOCALE, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone,
  }).format(new Date(iso));
}

export function formatTime(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(LOCALE, { hour: "numeric", minute: "2-digit", timeZone }).format(
    new Date(iso),
  );
}

export function formatDay(iso: string, timeZone?: string): string {
  return new Intl.DateTimeFormat(LOCALE, {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone,
  }).format(new Date(iso));
}

/** "14 Oct": a calendar date (YYYY-MM-DD) or timestamp, short. */
export function formatShortDate(value: string, timeZone?: string): string {
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00Z`) : new Date(value);
  return new Intl.DateTimeFormat(LOCALE, {
    day: "numeric",
    month: "short",
    timeZone: /^\d{4}-\d{2}-\d{2}$/.test(value) ? "UTC" : timeZone,
  }).format(date);
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

/** "3 days ago", "today", "yesterday". */
export function relativeDay(iso: string, now: Date = new Date()): string {
  const days = Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `${days} days ago`;
}

export function titleCase(text: string): string {
  return text.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const MODE_LABELS: Record<string, string> = {
  video: "Video call",
  in_person: "In person",
  phone: "Phone call",
};

export function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? titleCase(mode);
}

/** The first word of a full name, for greetings ("Hello, Asha"). */
export function firstName(fullName: string): string {
  return fullName.trim().split(/\s+/)[0] ?? fullName;
}
