import { vi } from "vitest";

/** State behind the mocked `next/navigation` (see tests/setup.ts). */
export const navigation = {
  pathname: "/",
  search: "",
  router: {
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  },
  reset() {
    this.pathname = "/";
    this.search = "";
    for (const fn of Object.values(this.router)) fn.mockReset();
  },
};
