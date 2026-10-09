/** Runtime schemas for API responses: the client validates what it receives. */
import { z } from "zod";

import { ROLES } from "@/lib/auth/roles";

export const roleSchema = z.enum(ROLES);

export const tokenOutSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
  csrf_token: z.string().min(1),
  user: z.object({
    id: z.string(),
    role: roleSchema,
    institution_id: z.string(),
  }),
});
export type TokenOut = z.infer<typeof tokenOutSchema>;

export const meSchema = z.object({
  id: z.string(),
  institution_id: z.string(),
  email: z.string(),
  full_name: z.string(),
  role: roleSchema,
  status: z.string(),
  permissions: z.array(z.string()),
});
export type Me = z.infer<typeof meSchema>;

export const acceptedSchema = z.object({ status: z.string() });
export type Accepted = z.infer<typeof acceptedSchema>;

export const problemSchema = z.object({
  title: z.string().optional(),
  detail: z.string().optional(),
  request_id: z.string().nullish(),
  errors: z
    .array(z.object({ loc: z.array(z.union([z.string(), z.number()])), msg: z.string() }))
    .optional(),
});
