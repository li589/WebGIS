// @vitest-environment jsdom
import { describe, expect, it, beforeEach, vi } from "vitest";

import { safeRedirect, isBackendApiPath } from "@/app/safe-redirect";
import { EXTRA_ROUTES, SPA_PATHS, SPA_ROUTES } from "@/app/route-paths";
import { router } from "@/app/router";
import { createPinia, setActivePinia } from "@/test-utils";
import { useAuthStore } from "@/stores/auth";
import type { AuthUser } from "@/services/auth-api";

// 导航会解析懒加载视图；真实 DashboardView 会拖入 MapLibre 等重型依赖
// （jsdom 下挂起超时）。此处 stub 掉两个视图，只测路由/守卫本身。
vi.mock("@/views/DashboardView.vue", () => ({ default: { template: "<div />" } }));
vi.mock("@/views/DeploymentConfigView.vue", () => ({
  default: { template: "<div />" },
}));

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

// ── 部署配置中心：admin 专属路由守卫（UX 层；后端 API 才是安全边界） ────────

function makeUser(role: AuthUser["role"]): AuthUser {
  return { id: 1, username: `u-${role}`, role, enabled: true } as AuthUser;
}

describe("deployment-config route admin guard", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("registers /deployment with requiresAdmin meta and a dedicated view", () => {
    const route = router.getRoutes().find((r) => r.path === "/deployment");
    expect(route?.name).toBe("deployment-config");
    expect(route?.meta?.requiresAdmin).toBe(true);
    expect(route?.meta?.public).toBeUndefined();
  });

  it("is whitelisted for post-login redirect", () => {
    expect(safeRedirect("/deployment")).toBe("/deployment");
  });

  it("redirects non-admin (standard/demo) back to dashboard", async () => {
    for (const role of ["standard", "demo"] as const) {
      const auth = useAuthStore();
      auth.user = makeUser(role);
      auth.bootstrapped = true;
      await router.push("/deployment");
      await router.isReady();
      expect(router.currentRoute.value.path, `role=${role}`).toBe("/");
    }
  });

  it("allows admin through to /deployment", async () => {
    const auth = useAuthStore();
    auth.user = makeUser("admin");
    auth.bootstrapped = true;
    await router.push("/deployment");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/deployment");
    expect(router.currentRoute.value.name).toBe("deployment-config");
  });

  it("keeps dashboard reachable for everyone (guard regression)", async () => {
    const auth = useAuthStore();
    auth.user = makeUser("standard");
    auth.bootstrapped = true;
    await router.push("/");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/");
  });
});
