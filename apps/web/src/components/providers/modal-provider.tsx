"use client";

import * as React from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Styles the confirm button as a destructive action. */
  destructive?: boolean;
}

export interface DialogOptions {
  title: string;
  description?: string;
  /** Rendered inside the dialog; call `close()` when done. */
  content: (close: () => void) => React.ReactNode;
}

interface ModalApi {
  /** Resolves true when confirmed, false when cancelled or dismissed. */
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  /** Opens a general-purpose dialog. */
  open: (options: DialogOptions) => void;
  close: () => void;
}

const ModalContext = React.createContext<ModalApi | null>(null);

type Active =
  { kind: "confirm"; options: ConfirmOptions } | { kind: "dialog"; options: DialogOptions };

/**
 * One modal host for the whole app. Confirmation prompts are built on AlertDialog (focus
 * starts on Cancel, Escape cancels) and general dialogs on Dialog; both trap focus and return
 * it to the trigger.
 */
export function ModalProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = React.useState<Active | null>(null);
  const [isOpen, setIsOpen] = React.useState(false);
  // Resolver of the confirmation currently on screen, if any.
  const pending = React.useRef<((value: boolean) => void) | null>(null);
  // Radix only restores focus to a <Trigger>, and these dialogs are opened programmatically,
  // so remember what had focus and give it back on close (WCAG 2.4.3 focus order).
  const returnFocus = React.useRef<HTMLElement | null>(null);
  const restoreFocus = React.useCallback((event: Event) => {
    event.preventDefault();
    returnFocus.current?.focus();
  }, []);
  const rememberFocus = () => {
    returnFocus.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
  };

  const settle = React.useCallback(
    (value: boolean) => {
      pending.current?.(value);
      pending.current = null;
      setIsOpen(false);
    },
    [pending],
  );

  const api = React.useMemo<ModalApi>(
    () => ({
      confirm: (options) =>
        new Promise<boolean>((resolve) => {
          rememberFocus();
          pending.current?.(false); // a newer prompt replaces an unanswered one
          pending.current = resolve;
          setActive({ kind: "confirm", options });
          setIsOpen(true);
        }),
      open: (options) => {
        rememberFocus();
        pending.current?.(false);
        pending.current = null;
        setActive({ kind: "dialog", options });
        setIsOpen(true);
      },
      close: () => settle(false),
    }),
    [settle],
  );

  return (
    <ModalContext.Provider value={api}>
      {children}

      {active?.kind === "confirm" && (
        <AlertDialog open={isOpen} onOpenChange={(open) => !open && settle(false)}>
          <AlertDialogContent onCloseAutoFocus={restoreFocus}>
            <AlertDialogHeader>
              <AlertDialogTitle>{active.options.title}</AlertDialogTitle>
              {active.options.description && (
                <AlertDialogDescription>{active.options.description}</AlertDialogDescription>
              )}
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{active.options.cancelLabel ?? "Cancel"}</AlertDialogCancel>
              <AlertDialogAction
                className={cn(
                  active.options.destructive && buttonVariants({ variant: "destructive" }),
                )}
                onClick={() => settle(true)}
              >
                {active.options.confirmLabel ?? "Confirm"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}

      {active?.kind === "dialog" && (
        <Dialog open={isOpen} onOpenChange={(open) => !open && settle(false)}>
          <DialogContent onCloseAutoFocus={restoreFocus}>
            <DialogHeader>
              <DialogTitle>{active.options.title}</DialogTitle>
              {active.options.description ? (
                <DialogDescription>{active.options.description}</DialogDescription>
              ) : (
                <DialogDescription className="sr-only">{active.options.title}</DialogDescription>
              )}
            </DialogHeader>
            <DialogBody content={active.options.content} onClose={() => settle(false)} />
          </DialogContent>
        </Dialog>
      )}
    </ModalContext.Provider>
  );
}

function DialogBody({
  content,
  onClose,
}: {
  content: DialogOptions["content"];
  onClose: () => void;
}) {
  return <>{content(onClose)}</>;
}

export function useModal(): ModalApi {
  const ctx = React.useContext(ModalContext);
  if (!ctx) throw new Error("useModal must be used inside <ModalProvider>");
  return ctx;
}
