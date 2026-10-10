/** Builds `?a=1&b=2` from the defined, non-empty values; empty when there are none. */
export type Query = Record<string, string | number | boolean | undefined | null>;

export function qs(params: Query): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
