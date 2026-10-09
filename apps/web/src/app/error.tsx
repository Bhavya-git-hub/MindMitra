"use client";

import { RouteError } from "@/components/states/route-error";

export default function Error(props: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="grid min-h-dvh place-items-center bg-calm px-4">
      <RouteError {...props} />
    </main>
  );
}
