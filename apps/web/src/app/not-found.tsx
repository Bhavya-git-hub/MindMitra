import { Compass } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <main className="grid min-h-dvh place-items-center bg-calm px-4">
      <div className="max-w-md space-y-4 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-full bg-secondary text-secondary-foreground">
          <Compass className="size-7" aria-hidden="true" />
        </span>
        <h1 className="text-2xl font-semibold">We can&apos;t find that page</h1>
        <p className="text-muted-foreground">
          The link may be old or mistyped. Nothing is wrong with your account.
        </p>
        <Button asChild>
          <Link href="/">Go to my space</Link>
        </Button>
      </div>
    </main>
  );
}
