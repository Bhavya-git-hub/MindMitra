import { z } from "zod";

/** Shared field rules, so every form words and checks them the same way. */

export const emailSchema = (requiredMessage = "Enter your email address") =>
  z.string().trim().min(1, requiredMessage).pipe(z.email("Enter a valid email address"));

/** Mirrors the API's password policy lengths (the API still has the final say). */
export const newPasswordSchema = z
  .string()
  .min(12, "Use at least 12 characters")
  .max(128, "Use at most 128 characters");
