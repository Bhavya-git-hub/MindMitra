/**
 * The events the API pushes over the real-time channel. They carry identifiers and fixed words
 * only: a view that hears one fetches the content through the normal, authorised API.
 */
import { z } from "zod";

export const realtimeEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("notification"),
    id: z.string(),
    notification_type: z.string(),
    title: z.string(),
  }),
  z.object({ type: z.literal("notifications_read") }),
  /** A message in the conversation with `with` (the other person's user id). */
  z.object({ type: z.literal("message"), with: z.string(), message_id: z.string() }),
  /** Messages in the conversation with `with` were read. */
  z.object({ type: z.literal("message_read"), with: z.string() }),
  z.object({ type: z.literal("appointment"), appointment_id: z.string(), event: z.string() }),
  /**
   * Not from the server: the connection came back, or the page came back into view. Anything
   * may have changed meanwhile, so views refresh.
   */
  z.object({ type: z.literal("resync") }),
]);

export type RealtimeEvent = z.infer<typeof realtimeEventSchema>;
export type RealtimeEventType = RealtimeEvent["type"];

/** Reads one decoded frame; protocol frames (ready, pong) and anything unknown give null. */
export function parseEvent(frame: unknown): RealtimeEvent | null {
  const parsed = realtimeEventSchema.safeParse(frame);
  return parsed.success && parsed.data.type !== "resync" ? parsed.data : null;
}
