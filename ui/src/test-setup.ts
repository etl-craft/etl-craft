import "@testing-library/jest-dom/vitest";

import { vi } from "vitest";

// jsdom has no layout observer; browser tests exercise resizing with the real API.
vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
