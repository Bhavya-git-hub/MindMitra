/**
 * Toast helpers over sonner. Use these instead of calling `toast` directly so wording and
 * durations stay consistent. Toasts are for brief confirmations; anything that needs action
 * belongs in an inline alert or a dialog.
 */
import { toast } from "sonner";

export const notify = {
  success: (message: string, description?: string) =>
    toast.success(message, { description, duration: 4000 }),
  info: (message: string, description?: string) =>
    toast.info(message, { description, duration: 5000 }),
  warning: (message: string, description?: string) =>
    toast.warning(message, { description, duration: 6000 }),
  /** Errors stay until dismissed so they cannot be missed. */
  error: (message: string, description?: string) =>
    toast.error(message, { description, duration: Infinity }),
  dismiss: (id?: string | number) => toast.dismiss(id),
};
