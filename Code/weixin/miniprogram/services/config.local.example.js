/**
 * 本地私有配置模板 —— 复制为 config.local.js 后填入真实值。
 *
 *   cp services/config.local.example.js services/config.local.js
 *
 * config.local.js 已在 .gitignore 中，不会入库；请勿把凭据提交到仓库。
 * 本文件保留在仓库中仅作为可复制的骨架。
 */

module.exports = {
  // 开发者工具模拟器直连本机后端：
  baseUrl: 'http://127.0.0.1:8000',
  // 真机预览 / 体验版改走 Cloudflare 隧道（HTTPS）：
  // baseUrl: 'https://api.<your-domain>',

  // 后端管理员账号（与 Code/backend/.env 的 BACKEND_ADMIN_USERNAME /
  // BACKEND_ADMIN_PASSWORD 保持一致；该 .env 不入库）。
  username: 'admin',
  password: '<BACKEND_ADMIN_PASSWORD>'
};
