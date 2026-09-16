/**
 * 小程序后端接入的「默认值」配置（入库，禁止写入任何真实凭据）。
 *
 * 真实值放在 services/config.local.js —— 该文件已 gitignore，不入库。
 * 新克隆仓库后请复制 services/config.local.example.js 为 config.local.js
 * 并填入 baseUrl / username / password；缺失时 api.js 会给出明确告警。
 *
 * baseUrl 的目标形态取决于运行环境：
 *  - 开发者工具（模拟器）：http://127.0.0.1:8000 —— 直连本机后端，最快，无需隧道；
 *  - 真机预览 / 体验版：必须 HTTPS，填后端已绑定的 Cloudflare 隧道域名
 *    （如 https://api.<your-domain>），并在小程序后台把该域名加入 request 合法域名
 *    （本地开发可依赖 project.config.json 的 setting.urlCheck=false 跳过校验）。
 */

module.exports = {
  baseUrl: 'http://127.0.0.1:8000',
  username: '',
  password: ''
};
