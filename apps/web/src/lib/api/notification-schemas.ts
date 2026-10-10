import { z } from "zod";

/** An in-app notification. Titles are fixed phrases and payloads hold identifiers only. */
export const notificationSchema = z.object({
  id: z.string(),
  type: z.string(),
  priority: z.string(),
  title: z.string(),
  payload: z.record(z.string(), z.string()),
  created_at: z.string(),
  read_at: z.string().nullable(),
});
export type AppNotification = z.infer<typeof notificationSchema>;

export const inboxSchema = z.object({
  items: z.array(notificationSchema),
  unread: z.number().int(),
});
export type Inbox = z.infer<typeof inboxSchema>;

export const unreadSchema = z.object({ unread: z.number().int() });
export const markedSchema = z.object({ marked_read: z.number().int() });
