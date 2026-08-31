/**
 * 本机 http://127.0.0.1:PORT → HTTPS 上游（默认 api.cgdas.dpdns.org）
 *
 * 用法：
 *   node api-proxy.mjs
 *   或 .\start-node.ps1
 *
 * 环境变量：
 *   CGDA_PROXY_TARGET  上游根 URL（默认 https://api.cgdas.dpdns.org）
 *   CGDA_PROXY_PORT    本地端口（默认 8000）
 */
import http from "node:http";
import https from "node:https";

const TARGET = (process.env.CGDA_PROXY_TARGET || "https://api.cgdas.dpdns.org").replace(
  /\/$/,
  "",
);
const PORT = Number(process.env.CGDA_PROXY_PORT || "8000");
const targetUrl = new URL(TARGET);

if (!Number.isFinite(PORT) || PORT <= 0 || PORT > 65535) {
  console.error(`Invalid CGDA_PROXY_PORT: ${process.env.CGDA_PROXY_PORT}`);
  process.exit(1);
}

http
  .createServer((req, res) => {
    const path = req.url || "/";
    const headers = { ...req.headers, host: targetUrl.hostname };
    delete headers["accept-encoding"];

    const upstream = https.request(
      {
        protocol: targetUrl.protocol,
        hostname: targetUrl.hostname,
        port: targetUrl.port || 443,
        path,
        method: req.method,
        headers,
      },
      (up) => {
        res.writeHead(up.statusCode || 502, up.headers);
        up.pipe(res);
      },
    );

    upstream.on("error", (err) => {
      res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
      res.end(`upstream error: ${err.message}`);
    });

    req.pipe(upstream);
  })
  .listen(PORT, "127.0.0.1", () => {
    console.log(`proxy http://127.0.0.1:${PORT} -> ${TARGET}`);
    console.log("Keep this window open. Test: http://localhost:" + PORT + "/health");
  });
