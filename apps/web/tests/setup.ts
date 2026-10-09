import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Synthetic values only. The signing secret is random per run, never a real one.
process.env.SESSION_SECRET = "test-".concat(crypto.randomUUID(), crypto.randomUUID());
process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.useRealTimers();
});

// jsdom lacks these browser APIs that Radix UI and Recharts rely on.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia;
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};

// App Router hooks need a router; tests drive and inspect this fake one.
vi.mock("next/navigation", async () => {
  const { navigation } = await import("./helpers/navigation");
  return {
    useRouter: () => navigation.router,
    usePathname: () => navigation.pathname,
    useSearchParams: () => new URLSearchParams(navigation.search),
    redirect: vi.fn(),
    notFound: vi.fn(),
  };
});

afterEach(async () => {
  const { navigation } = await import("./helpers/navigation");
  navigation.reset();
});
