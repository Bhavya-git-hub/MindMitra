/** Typed wrappers for the AI companion endpoints. The AI itself is only ever reached through
 * the API; nothing here talks to a model or holds a key. */
import { z } from "zod";

import type { ApiClient } from "./client";
import {
  companionConversationSchema,
  companionDetailSchema,
  companionExchangeSchema,
  companionStatusSchema,
} from "./companion-schemas";

export function createCompanionApi(client: ApiClient) {
  return {
    status: () => client.request("/companion/status", { schema: companionStatusSchema }),
    conversations: () =>
      client.request("/companion/conversations", { schema: z.array(companionConversationSchema) }),
    start: () =>
      client.request("/companion/conversations", {
        method: "POST",
        schema: companionConversationSchema,
      }),
    conversation: (id: string) =>
      client.request(`/companion/conversations/${encodeURIComponent(id)}`, {
        schema: companionDetailSchema,
      }),
    send: (id: string, content: string) =>
      client.request(`/companion/conversations/${encodeURIComponent(id)}/messages`, {
        method: "POST",
        body: { content },
        schema: companionExchangeSchema,
      }),
    remove: (id: string) =>
      client.request(`/companion/conversations/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),
  };
}

export type CompanionApi = ReturnType<typeof createCompanionApi>;
