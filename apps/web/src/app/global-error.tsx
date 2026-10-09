"use client";

import "./globals.css";

/** Last-resort boundary: replaces the root layout, so it brings its own <html> and no providers. */
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <main className="grid min-h-dvh place-items-center bg-calm px-4">
          <div role="alert" className="max-w-md space-y-4 text-center">
            <h1 className="text-2xl font-semibold">Something went wrong</h1>
            <p className="text-muted-foreground">
              This is on our side, not yours. Please try again.
            </p>
            <button
              type="button"
              onClick={reset}
              className="inline-flex h-10 items-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground"
            >
              Try again
            </button>
          </div>
        </main>
      </body>
    </html>
  );
}
