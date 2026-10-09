import type { FieldValues, Path, UseFormReturn } from "react-hook-form";

import { describeError, isApiError } from "@/lib/api/errors";

/**
 * Copies the API's per-field validation messages onto a react-hook-form form and returns the
 * message to show above the form (null when every problem was attached to a field).
 *
 * `aliases` maps an API field name to the form's field name (the API calls the reset-password
 * field `password` in its validation errors, for example).
 */
export function applyApiErrors<T extends FieldValues>(
  form: UseFormReturn<T>,
  error: unknown,
  aliases: Record<string, string> = {},
): string | null {
  if (isApiError(error) && error.status === 422) {
    const known = new Set(Object.keys(form.getValues()));
    let attached = 0;
    for (const [apiField, message] of Object.entries(error.fieldErrors())) {
      const field = aliases[apiField] ?? apiField;
      if (known.has(field)) {
        form.setError(field as Path<T>, { type: "server", message: capitalise(message) });
        attached += 1;
      }
    }
    if (attached > 0) return "Please check the highlighted fields and try again.";
  }
  return describeError(error);
}

function capitalise(message: string): string {
  return message.charAt(0).toUpperCase() + message.slice(1);
}
