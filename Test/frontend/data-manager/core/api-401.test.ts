/**
 * data-manager 独立 HTTP 层（core/api.ts writeFetch）401 语义：
 * 与 services/_http.ts 对齐——触发会话过期跳转并抛 SessionExpiredError；
 * 分块上传对 401 不做网络型重试（避免重试风暴与静默吞掉登录跳转）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionExpiredError } from "@/services/http-errors";
// 静态导入：模块 transform 不得计入测试体 5s 预算（满载机器上动态 import 会假性超时）
import { chunkedUpload, listImportJobs } from "@/data-manager/core/api";

const handleSessionExpiredMock = vi.fn();

vi.mock("@/services/session-expired", () => ({
  handleSessionExpired: (...args: unknown[]) =>
    handleSessionExpiredMock(...args),
  isAuthBootstrapPath: (path: string) => {
    const normalized = path.split("?")[0] ?? path;
    return (
      normalized === "/auth/login" ||
      normalized === "/auth/config" ||
      normalized === "/auth/me" ||
      normalized === "/auth/logout"
    );
  },
}));

describe("data-manager core api 401", () => {
  beforeEach(() => {
    handleSessionExpiredMock.mockClear();
    vi.stubGlobal("fetch", vi.fn());
    const storage = {
      getItem: () => null,
      setItem: () => undefined,
      removeItem: () => undefined,
      clear: () => undefined,
    };
    vi.stubGlobal("localStorage", storage);
    vi.stubGlobal("sessionStorage", storage);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("redirects to login and throws SessionExpiredError on 401 (listImportJobs)", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(listImportJobs()).rejects.toBeInstanceOf(SessionExpiredError);
    expect(handleSessionExpiredMock).toHaveBeenCalledWith(
      "/import/jobs?limit=20",
    );
  });

  it("chunked upload surfaces 401 once without retry storm", async () => {
    const file = new File([new Uint8Array(8).fill(1)], "demo.tif", {
      type: "image/tiff",
    });
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = (init?.method || "GET").toUpperCase();
        if (
          url.includes("/import/upload/resumable/init") &&
          method === "POST"
        ) {
          return new Response(
            JSON.stringify({
              upload_id: "up-1",
              chunk_size: 4,
              total_chunks: 2,
            }),
            {
              status: 200,
              headers: { "Content-Type": "application/json" },
            },
          );
        }
        return new Response(JSON.stringify({ detail: "Unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" },
        });
      },
    );

    await expect(chunkedUpload(file)).rejects.toBeInstanceOf(
      SessionExpiredError,
    );
    expect(handleSessionExpiredMock).toHaveBeenCalled();
    // 2 个分块并发首发各一次；重试风暴会令同一索引出现第二次
    const chunkIndices = fetchMock.mock.calls
      .filter(([input, init]) => {
        const url = String(input);
        const method = (
          (init as RequestInit | undefined)?.method || "GET"
        ).toUpperCase();
        return url.includes("/chunk/") && method === "POST";
      })
      .map(([input]) => {
        const m = /\/chunk\/(\d+)/.exec(String(input));
        return m ? Number(m[1]) : -1;
      })
      .sort((a, b) => a - b);
    expect(chunkIndices).toEqual([0, 1]);
  });
});
