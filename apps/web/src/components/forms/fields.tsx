"use client";

import { Eye, EyeOff, Loader2 } from "lucide-react";
import * as React from "react";
import { useFormContext, type FieldPath, type FieldValues } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

/**
 * Form field components for react-hook-form + zod. Each wires label, description and error
 * message to the control (aria-describedby, aria-invalid) so forms are accessible by default.
 * Use inside <Form {...form}>.
 */

interface BaseFieldProps<T extends FieldValues> {
  name: FieldPath<T>;
  label: string;
  description?: string;
}

export function TextField<T extends FieldValues>({
  name,
  label,
  description,
  ...inputProps
}: BaseFieldProps<T> &
  Omit<React.ComponentProps<typeof Input>, "name" | "value" | "defaultValue" | "onChange">) {
  const { control } = useFormContext<T>();
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input {...inputProps} {...field} value={field.value ?? ""} />
          </FormControl>
          {description && <FormDescription>{description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export function PasswordField<T extends FieldValues>({
  name,
  label,
  description,
  autoComplete = "current-password",
  ...inputProps
}: BaseFieldProps<T> &
  Omit<
    React.ComponentProps<typeof Input>,
    "name" | "value" | "defaultValue" | "onChange" | "type"
  >) {
  const { control } = useFormContext<T>();
  const [visible, setVisible] = React.useState(false);
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <div className="relative">
            <FormControl>
              <Input
                {...inputProps}
                {...field}
                value={field.value ?? ""}
                type={visible ? "text" : "password"}
                autoComplete={autoComplete}
                className="pr-11"
              />
            </FormControl>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute top-0 right-0 size-10"
              aria-label={visible ? "Hide password" : "Show password"}
              aria-pressed={visible}
              onClick={() => setVisible((v) => !v)}
            >
              {visible ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
            </Button>
          </div>
          {description && <FormDescription>{description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export function TextareaField<T extends FieldValues>({
  name,
  label,
  description,
  ...props
}: BaseFieldProps<T> &
  Omit<React.ComponentProps<typeof Textarea>, "name" | "value" | "defaultValue" | "onChange">) {
  const { control } = useFormContext<T>();
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Textarea {...props} {...field} value={field.value ?? ""} />
          </FormControl>
          {description && <FormDescription>{description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export function SelectField<T extends FieldValues>({
  name,
  label,
  description,
  options,
  placeholder = "Choose…",
}: BaseFieldProps<T> & {
  options: { value: string; label: string }[];
  placeholder?: string;
}) {
  const { control } = useFormContext<T>();
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <Select value={field.value ?? ""} onValueChange={field.onChange} name={field.name}>
            <FormControl>
              <SelectTrigger onBlur={field.onBlur} ref={field.ref}>
                <SelectValue placeholder={placeholder} />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              {options.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {description && <FormDescription>{description}</FormDescription>}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export function CheckboxField<T extends FieldValues>({
  name,
  label,
  description,
}: Omit<BaseFieldProps<T>, "label"> & { label: React.ReactNode }) {
  const { control } = useFormContext<T>();
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <div className="flex items-start gap-3">
            <FormControl>
              <Checkbox
                checked={Boolean(field.value)}
                onCheckedChange={(checked) => field.onChange(checked === true)}
                onBlur={field.onBlur}
                ref={field.ref}
                name={field.name}
                className="mt-0.5"
              />
            </FormControl>
            <div className="grid gap-1">
              <FormLabel className="font-normal leading-snug">{label}</FormLabel>
              {description && <FormDescription>{description}</FormDescription>}
            </div>
          </div>
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

/** Submit button that shows progress and blocks double submits without losing its label. */
export function SubmitButton({
  pending,
  children,
  pendingLabel = "Please wait…",
  className,
}: {
  pending: boolean;
  children: React.ReactNode;
  pendingLabel?: string;
  className?: string;
}) {
  return (
    <Button type="submit" disabled={pending} aria-busy={pending} className={className}>
      {pending ? (
        <>
          <Loader2 className="animate-spin" aria-hidden="true" />
          {pendingLabel}
        </>
      ) : (
        children
      )}
    </Button>
  );
}
