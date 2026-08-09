// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { safeRedirect, isBackendApiPath } from "@/app/safe-redirect";
import { EXTRA_ROUTES, SPA_PATHS, SPA_ROUTES } from "@/app/route-paths";
import { router } from "@/app/router";

describe("safeRedirect", () => {
  it("allows dashboard root", () => {
    expect(safeRedirect("/")).toBe("/");
  });

  it("rejects open redirects", () => {
    expect(safeRedirect("//evil.example")).toBe("/");
    expect(safeRedirect("https://evil.example")).toBe("/");
    expect(safeRedirect(undefined)).toBe("/");
  });

  it("rejects encoded slashes and login loop targets", () => {
    expect(safeRedirect("/%2fevil")).toBe("/");
    expect(safeRedirect("/%2Fevil")).toBe("/");
    expect(safeRedirect("/login")).toBe("/");
    expect(safeRedirect("/login?redirect=/")).toBe("/");
  });

  it("rejects backend API paths mistaken as SPA routes", () => {
    expect(safeRedirect("/config/api-keys")).toBe("/");
    expect(safeRedirect("/auth/me")).toBe("/");
    expect(safeRedirect("/runtime/status")).toBe("/");
    expect(isBackendApiPath("/config/api-keys")).toBe(true);
  });

  it("rejects unknown SPA paths that would 404", () => {
    expect(safeRedirect("/layers")).toBe("/");
    expect(safeRedirect("/unknown-page")).toBe("/");
  });
});

describe("route-path single source of truth", () => {
  it("every SPA_ROUTES entry is whitelisted for safeRedirect", () => {
    for (const route of SPA_ROUTES) {
      expect(
        SPA_PATHS.has(route.path),
        `missing whitelist: ${route.path}`,
      ).toBe(true);
      expect(
        safeRedirect(route.path),
        `safeRedirect blocked: ${route.path}`,
      ).toBe(route.path);
    }
  });

  it("SPA_PATHS only contains paths registered in the router", () => {
    const registered = new Set(router.getRoutes().map((r) => r.path));
    for (const path of SPA_PATHS) {
      expect(registered.has(path), `unregistered whitelist path: ${path}`).toBe(
        true,
      );
    }
  });

  it("router is built from the same definitions (no drift)", () => {
    const routerPaths = router
      .getRoutes()
      .map((r) => r.path)
      .sort();
    const definedPaths = [
      ...SPA_ROUTES.map((r) => r.path),
      ...EXTRA_ROUTES.map((r) => r.path),
    ].sort();
    expect(routerPaths).toEqual(definedPaths);
    expect(router.getRoutes().some((r) => r.name === "login")).toBe(true);
  });

  it("login and not-found are excluded from the whitelist", () => {
    for (const extra of EXTRA_ROUTES) {
      expect(SPA_PATHS.has(extra.path)).toBe(false);
    }
  });
});
