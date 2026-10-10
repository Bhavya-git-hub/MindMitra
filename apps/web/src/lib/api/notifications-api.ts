/** Everyone's own notifications: list, count unread, mark read. */
import type { ApiClient } from "./client";
import { inboxSchema, markedSchema, unreadSchema } from "./notification-schemas";
import { qs } from "./query-string";

export function createNotificationsApi(client: ApiClient) {
  return {
    inbox: (options: { unread?: boolean; before?: string; limit?: number } = {}) =>
      client.request(`/me/notifications${qs(options)}`, { schema: inboxSchema }),
    unreadCount: () => client.request("/me/notifications/unread-count", { schema: unreadSchema }),
    markRead: (id: string) => client.request(`/me/notifications/${id}/read`, { method: "POST" }),
    markAllRead: () =>
      client.request("/me/notifications/read-all", { method: "POST", schema: markedSchema }),
  };
}

export type NotificationsApi = ReturnType<typeof createNotificationsApi>;
