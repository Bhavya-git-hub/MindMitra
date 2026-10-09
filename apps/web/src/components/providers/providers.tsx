"use client";

import { ThemeProvider } from "next-themes";
import * as React from "react";

import { ModalProvider } from "@/components/providers/modal-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/lib/auth/auth-context";

/** Every client-side provider, in one place. The CSP nonce lets next-themes' inline script run. */
export function Providers({ children, nonce }: { children: React.ReactNode; nonce?: string }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      nonce={nonce}
      disableTransitionOnChange
    >
      <TooltipProvider delayDuration={200}>
        <ModalProvider>
          <AuthProvider>
            {children}
            <Toaster />
          </AuthProvider>
        </ModalProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
