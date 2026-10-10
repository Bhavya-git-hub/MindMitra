/** Response shapes of the AI companion endpoints (`/companion`). */
import { z } from "zod";

import { crisisContactSchema } from "./student-schemas";

export const companionStatusSchema = z.object({
  available: z.boolean(),
  /** "switched_off" (by the institution or deployment) or "not_configured". */
  reason: z.string().nullable(),
  daily_limit: z.number().int(),
  remaining_today: z.number().int(),
  keeps_history: z.boolean(),
  retention_hours: z.number().int(),
  disclaimer: z.string(),
});
export type CompanionStatus = z.infer<typeof companionStatusSchema>;

export const companionConversationSchema = z.object({
  id: z.string(),
  status: z.string(),
  started_at: z.string(),
  last_message_at: z.string().nullable(),
  expires_at: z.string().nullable(),
});
export type CompanionConversation = z.infer<typeof companionConversationSchema>;

export const companionMessageSchema = z.object({
  id: z.string(),
  seq: z.number().int(),
  role: z.enum(["user", "assistant"]),
  /** How an assistant message was made: reply, crisis, redirect, fallback, unavailable. */
  kind: z.string().nullable(),
  content: z.string(),
  show_support: z.boolean(),
  created_at: z.string(),
});
export type CompanionMessage = z.infer<typeof companionMessageSchema>;

export const companionDetailSchema = z.object({
  conversation: companionConversationSchema,
  messages: z.array(companionMessageSchema),
});
export type CompanionDetail = z.infer<typeof companionDetailSchema>;

export const companionSupportSchema = z.object({
  /** "crisis": a person was alerted. "gentle": contacts are offered, nobody was alerted. */
  level: z.enum(["crisis", "gentle"]),
  escalated: z.boolean(),
  care_team_notified: z.boolean(),
  about_someone_else: z.boolean(),
  contacts: z.array(crisisContactSchema),
});
export type CompanionSupport = z.infer<typeof companionSupportSchema>;

export const companionExchangeSchema = z.object({
  conversation: companionConversationSchema,
  message: companionMessageSchema,
  reply: companionMessageSchema,
  support: companionSupportSchema.nullable(),
  disclaimer: z.string(),
});
export type CompanionExchange = z.infer<typeof companionExchangeSchema>;
