/* ============================================================
   CGDA 问题反馈中心 · feedback.js
   纯静态页面逻辑：IndexedDB 本地存储、附件安全校验、限流、
   XSS 防护（所有用户数据一律 textContent 渲染，绝不经 innerHTML）、
   公告/处理进展轮询合并、后端健康检查、复制/粘贴。

   安全设计说明：
   - 渲染：动态内容仅通过 createElement + textContent 注入；
     innerHTML 仅用于本文件内的常量图标 SVG（不含任何用户数据）。
   - 注入防护：输入清洗（去控制字符 + 截断）；文本附件预览走 <pre> textContent。
   - 附件：扩展名白名单 + 图片魔数校验 + 单文件/总数/总大小上限 + 文件名净化。
   - 限流：提交间隔 ≥15s；10 分钟 ≤5 条、1 小时 ≤20 条、24 小时 ≤60 条。
   - 蜜罐 + 加载时序检查，拦截最粗暴的机器人提交。
   ============================================================ */
'use strict';

(function () {
  /* ---------- 常量 ---------- */
  var ANN_URL = 'data/announcements.json';
  var HEALTH_URL = '/health';
  var API_BASE = '/feedback/api'; // 在线轨：后端在线时上传/查询（离线自动降级本地导出）
  var ANN_POLL_MS = 60 * 1000;
  var HEALTH_POLL_MS = 30 * 1000;
  var MB = 1024 * 1024;

  var K_IDENTITY = 'cgda-fb-identity';
  var K_SUBMITS = 'cgda-fb-submits';
  var K_DRAFT = 'cgda-fb-draft';
  var K_LS_REPORTS = 'cgda-fb-reports-fallback'; // IDB 不可用时的降级存储

  var LIMITS = { maxFiles: 10, totalBytes: 40 * MB };
  var FILE_KINDS = [
    { kind: 'image', label: '图片', exts: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'], max: 10 * MB, preview: 'image' },
    { kind: 'text', label: '文本/代码', exts: ['txt', 'log', 'json', 'csv', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf', 'md', 'py', 'js', 'mjs', 'cjs', 'ts', 'vue', 'html', 'htm', 'css', 'scss', 'less', 'sql', 'r', 'sh', 'ps1', 'bat', 'env'], max: 2 * MB, preview: 'text' },
    { kind: 'data', label: '数据/压缩', exts: ['zip', 'gz', 'tgz', 'tar', '7z', 'mat', 'nc', 'h5', 'hdf', 'npy', 'npz', 'pkl', 'tif', 'tiff', 'grib', 'grib2'], max: 25 * MB, preview: 'none' }
  ];
  var BLOCKED_EXTS = ['exe', 'dll', 'msi', 'scr', 'apk', 'jar', 'com', 'pif', 'vbs', 'vbe', 'wsf', 'ws', 'lnk', 'iso', 'dmg', 'deb', 'rpm', 'app', 'command', 'reg', 'hta', 'cpl'];

  var RATE = {
    minIntervalMs: 15000,
    windows: [
      { label: '10 分钟', ms: 10 * 60 * 1000, max: 5 },
      { label: '1 小时', ms: 60 * 60 * 1000, max: 20 },
      { label: '24 小时', ms: 24 * 60 * 60 * 1000, max: 60 }
    ]
  };

  var STATUS = {
    submitted: { label: '已提交', tone: 'info' },
    received: { label: '已受理', tone: 'info' },
    in_progress: { label: '处理中', tone: 'warn' },
    needs_info: { label: '待补充信息', tone: 'warn' },
    fixed: { label: '已修复', tone: 'ok' },
    closed: { label: '已关闭', tone: 'muted' },
    rejected: { label: '不予处理', tone: 'danger' }
  };
  var SEVERITY = { low: '低', medium: '中', high: '高', critical: '紧急' };
  var CATEGORY = {
    functional: '功能缺陷', data: '数据显示异常', workflow: '工作流问题', performance: '性能问题',
    ui: '界面与交互', ingest: '数据接入', deploy: '部署与运维', security: '安全相关', other: '其他'
  };
  var ROLES = { researcher: '研究员', engineer: '工程师', ops: '运维', student: '学生', other: '其他' };

  /* ---------- 常量图标（仅静态 SVG，安全） ---------- */
  function svg(paths, vb) {
    return '<svg class="ic" viewBox="' + (vb || '0 0 24 24') + '" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
  }
  var ICONS = {
    copy: svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
    download: svg('<path d="M21 15v3.5A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5V15M12 3v13M7.5 11.5 12 16l4.5-4.5"/>'),
    trash: svg('<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6"/>'),
    eye: svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
    eyeOff: svg('<path d="M17.94 17.94A10.5 10.5 0 0 1 12 19c-6.5 0-10-7-10-7a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A10.5 10.5 0 0 1 12 4c6.5 0 10 7 10 7a18.5 18.5 0 0 1-3.16 4.19M14.12 14.12a3 3 0 1 1-4.24-4.24M3 3l18 18"/>'),
    image: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>'),
    file: svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z"/><path d="M14 2v6h6"/>'),
    archive: svg('<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v10a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V9M10 13h4"/>'),
    check: svg('<path d="M4.5 12.5 10 18 19.5 6.5"/>'),
    alert: svg('<path d="M12 8v5M12 16.5h.01"/><path d="M10.3 3.6 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z"/>'),
    info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M12 11v5"/>'),
    inbox: svg('<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1Z"/>'),
    upload: svg('<path d="M21 15v3.5A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5V15M12 3v13M7.5 8.5 12 4l4.5 4.5"/>'),
    wrench: svg('<path d="M14.7 6.3a4.5 4.5 0 0 0-6 6L3.5 17.5a1.4 1.4 0 0 0 2 2l5.2-5.2a4.5 4.5 0 0 0 6-6l-2.6 2.6-2-2 2.6-2.6Z"/>'),
    wrench: svg('<path d="M14.7 6.3a4.5 4.5 0 0 0-6 6L3.5 17.5a1.4 1.4 0 0 0 2 2l5.2-5.2a4.5 4.5 0 0 0 6-6l-2.6 2.6-2-2 2.6-2.6Z"/>'),
    chat: svg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10Z"/>')
  };

  /* ---------- 基础工具 ---------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v == null) return;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k === 'html') n.innerHTML = v; // 仅限本文件常量图标
        else if (k.indexOf('on') === 0) n.addEventListener(k.slice(2), v);
        else n.setAttribute(k, String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null) continue;
      n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return n;
  }
  function debounce(fn, ms) {
    var t = null;
    return function () {
      var self = this, args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(self, args); }, ms);
    };
  }
  function fmtBytes(n) {
    if (!n) return '0 B';
    if (n < 1024) return n + ' B';
    if (n < MB) return (n / 1024).toFixed(1) + ' KB';
    return (n / MB).toFixed(2) + ' MB';
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtDateTime(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  function fmtRelative(ts) {
    var s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return '刚刚';
    if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
    if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
    return Math.floor(s / 86400) + ' 天前';
  }
  function uid(len) {
    var ABC = '23456789ABCDEFGHJKMNPQRSTUVWXYZ';
    var buf = new Uint8Array(len || 6);
    crypto.getRandomValues(buf);
    var out = '';
    for (var i = 0; i < buf.length; i++) out += ABC[buf[i] % ABC.length];
    return out;
  }
  function clean(s, max) {
    return String(s == null ? '' : s)
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
      .trim()
      .slice(0, max);
  }
  function sanitizeFileName(name) {
    var n = String(name || '').replace(/\\/g, '/');
    n = n.slice(n.lastIndexOf('/') + 1);
    n = n.replace(/[\u0000-\u001f\u007f]/g, '').replace(/^\.+/, '').trim();
    if (n.length > 100) {
      var dot = n.lastIndexOf('.');
      n = dot > 0 ? n.slice(0, dot).slice(0, 80) + '…' + n.slice(dot) : n.slice(0, 100);
    }
    return n || 'unnamed';
  }
  function lsGet(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch (e) { return fallback; }
  }
  function lsSet(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); return true; } catch (e) { return false; }
  }

  /* ---------- Toast ---------- */
  var toastStack = null;
  function toast(msg, type) {
    if (!toastStack) return;
    var iconHtml = type === 'ok' ? ICONS.check : (type === 'err' ? ICONS.alert : ICONS.info);
    var t = el('div', { class: 'toast toast-' + (type || 'info'), html: iconHtml }, el('span', { text: msg }));
    toastStack.appendChild(t);
    setTimeout(function () {
      t.classList.add('out');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 320);
    }, 3600);
  }

  /* ---------- 复制（含非安全上下文降级） ---------- */
  function copyText(text) {
    return new Promise(function (resolve) {
      var done = function (ok) { resolve(ok); };
      if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () {
          done(legacyCopy(text));
        });
      } else {
        done(legacyCopy(text));
      }
    });
  }
  function legacyCopy(text) {
    try {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:-9999px;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, text.length);
      var ok = document.execCommand('copy');
      ta.parentNode.removeChild(ta);
      return ok;
    } catch (e) { return false; }
  }
  function copyAndToast(text, okMsg) {
    copyText(text).then(function (ok) {
      toast(ok ? (okMsg || '已复制到剪贴板') : '复制失败，请手动选择文本复制', ok ? 'ok' : 'err');
    });
  }

  /* ---------- IndexedDB 存储（含降级） ---------- */
  var idbUsable = null;
  function idbOpen() {
    return new Promise(function (resolve, reject) {
      if (!('indexedDB' in window)) return reject(new Error('no-idb'));
      var req = indexedDB.open('cgda-feedback', 1);
      req.onupgradeneeded = function () {
        try { req.result.createObjectStore('reports', { keyPath: 'id' }); } catch (e) { /* 忽略重复建表 */ }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error('idb-open-failed')); };
      req.onblocked = function () { reject(new Error('idb-blocked')); };
    });
  }
  function idbTx(mode, fn) {
    return idbOpen().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction('reports', mode);
        var store = tx.objectStore('reports');
        var out = fn(store);
        tx.oncomplete = function () { resolve(out && out.result !== undefined ? out.result : undefined); };
        tx.onerror = function () { reject(tx.error || new Error('idb-tx-failed')); };
        tx.onabort = function () { reject(tx.error || new Error('idb-abort')); };
      });
    });
  }
  function storePut(report) {
    return idbTx('readwrite', function (s) { s.put(report); }).then(function () { return 'idb'; })
      .catch(function (e) {
        // 降级：localStorage 仅存元数据（不含附件二进制）
        var list = lsGet(K_LS_REPORTS, []);
        var lite = JSON.parse(JSON.stringify(stripBlobs(report)));
        list = list.filter(function (r) { return r.id !== report.id; });
        list.push(lite);
        while (list.length > 100) list.shift();
        if (!lsSet(K_LS_REPORTS, list)) throw e;
        return 'ls';
      });
  }
  function storeAll() {
    return idbTx('readonly', function (s) { return s.getAll(); }).then(function (rows) { return rows || []; })
      .catch(function () { return lsGet(K_LS_REPORTS, []); });
  }
  function storeDelete(id) {
    return idbTx('readwrite', function (s) { s.delete(id); })
      .catch(function () {
        var list = lsGet(K_LS_REPORTS, []).filter(function (r) { return r.id !== id; });
        lsSet(K_LS_REPORTS, list);
      });
  }
  function storeClear() {
    return idbTx('readwrite', function (s) { s.clear(); })
      .catch(function () { lsSet(K_LS_REPORTS, []); });
  }
  function stripBlobs(report) {
    var copy = {};
    Object.keys(report).forEach(function (k) {
      if (k === 'attachments') {
        copy.attachments = (report.attachments || []).map(function (a) {
          return { id: a.id, name: a.name, ext: a.ext, size: a.size, mime: a.mime, kind: a.kind, kindLabel: a.kindLabel, blobMissing: true };
        });
      } else copy[k] = report[k];
    });
    return copy;
  }

  /* ---------- 身份 ---------- */
  var identity = lsGet(K_IDENTITY, null) || {};
  if (!identity.deviceId) {
    identity.deviceId = 'U-' + uid(6);
    lsSet(K_IDENTITY, identity);
  }
  function saveIdentity() { lsSet(K_IDENTITY, identity); }
  function identityDisplay() {
    var name = clean(identity.name, 40) || '匿名用户';
    var role = ROLES[identity.role] || ROLES.other;
    return name + '（' + role + '）· ' + identity.deviceId;
  }
  function updateIdentityStrip() {
    var t = $('identity-strip-text');
    if (t) t.textContent = '将以 ' + identityDisplay() + ' 提交';
    var d = $('device-id');
    if (d) d.textContent = identity.deviceId;
  }

  /* ---------- 限流 ---------- */
  function getSubmits() {
    var v = lsGet(K_SUBMITS, []);
    return Array.isArray(v) ? v.filter(function (n) { return typeof n === 'number'; }) : [];
  }
  function checkRate() {
    var now = Date.now();
    var subs = getSubmits().filter(function (t) { return now - t < RATE.windows[2].ms; });
    if (subs.length) {
      var since = now - subs[subs.length - 1];
      if (since < RATE.minIntervalMs) {
        var wait = Math.ceil((RATE.minIntervalMs - since) / 1000);
        return { ok: false, msg: '提交过于频繁，请 ' + wait + ' 秒后再试' };
      }
    }
    for (var i = 0; i < RATE.windows.length; i++) {
      var w = RATE.windows[i];
      var cnt = subs.filter(function (t) { return now - t < w.ms; }).length;
      if (cnt >= w.max) return { ok: false, msg: '已达到提交上限（' + w.max + ' 条 / ' + w.label + '），请稍后再试' };
    }
    return { ok: true };
  }
  function recordSubmit() {
    var subs = getSubmits();
    subs.push(Date.now());
    lsSet(K_SUBMITS, subs);
  }

  /* ---------- 环境信息 ---------- */
  var tzName = 'UTC';
  try { tzName = Intl.DateTimeFormat().resolvedOptions().timeZone || tzName; } catch (e) { /* 保持默认 */ }
  var lastHealth = 'unknown';
  function collectEnv() {
    var n = navigator, s = screen;
    return {
      pageUrl: String(location.href).slice(0, 500),
      referrer: String(document.referrer || '').slice(0, 500),
      userAgent: String(n.userAgent || '').slice(0, 400),
      platform: String(n.platform || ''),
      language: String(n.language || ''),
      screen: s ? s.width + 'x' + s.height : '',
      viewport: window.innerWidth + 'x' + window.innerHeight,
      devicePixelRatio: String(window.devicePixelRatio || 1),
      timezone: tzName + ' (UTC' + offsetStr() + ')',
      online: String(!!n.onLine),
      backendHealth: lastHealth,
      cookieEnabled: String(!!n.cookieEnabled)
    };
  }
  function offsetStr() {
    var m = -new Date().getTimezoneOffset();
    var sign = m >= 0 ? '+' : '-';
    var abs = Math.abs(m);
    return sign + pad(Math.floor(abs / 60)) + ':' + pad(abs % 60);
  }

  /* ---------- 附件 ---------- */
  var attachments = []; // { id, name, ext, size, mime, kind, kindLabel, blob, thumb, excerpt, noPreview, _url, _open }
  function extOf(name) {
    var parts = String(name).split('.');
    return parts.length > 1 ? parts.pop().toLowerCase() : '';
  }
  function sniffImageMime(u8) {
    if (u8.length < 12) return null;
    if (u8[0] === 0x89 && u8[1] === 0x50 && u8[2] === 0x4e && u8[3] === 0x47) return 'image/png';
    if (u8[0] === 0xff && u8[1] === 0xd8 && u8[2] === 0xff) return 'image/jpeg';
    if (u8[0] === 0x47 && u8[1] === 0x49 && u8[2] === 0x46) return 'image/gif';
    if (u8[0] === 0x42 && u8[1] === 0x4d) return 'image/bmp';
    if (u8[0] === 0x52 && u8[1] === 0x49 && u8[2] === 0x46 && u8[3] === 0x46 &&
        u8[8] === 0x57 && u8[9] === 0x45 && u8[10] === 0x42 && u8[11] === 0x50) return 'image/webp';
    return null;
  }
  function blobSlice(buf) {
    return buf.slice(0, 4096).arrayBuffer().then(function (ab) {
      return new Uint8Array(ab);
    });
  }
  function readTextHead(file, maxBytes) {
    return file.slice(0, maxBytes).arrayBuffer().then(function (ab) {
      for (var i = 0; i < ab.byteLength; i++) {
        if (new Uint8Array(ab)[i] === 0) return null; // 二进制
      }
      return new TextDecoder('utf-8', { fatal: false }).decode(ab);
    }).catch(function () { return null; });
  }
  function makeThumb(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        try {
          var MAX = 420;
          var scale = Math.min(1, MAX / Math.max(img.naturalWidth || 1, img.naturalHeight || 1));
          var w = Math.max(1, Math.round((img.naturalWidth || 1) * scale));
          var h = Math.max(1, Math.round((img.naturalHeight || 1) * scale));
          var cv = document.createElement('canvas');
          cv.width = w; cv.height = h;
          cv.getContext('2d').drawImage(img, 0, 0, w, h);
          var data = cv.toDataURL('image/webp', 0.8);
          if (data.indexOf('data:image/webp') !== 0) data = cv.toDataURL('image/png');
          if (data.length > 180000) data = cv.toDataURL('image/jpeg', 0.7);
          resolve(data);
        } catch (e) { resolve(null); }
        URL.revokeObjectURL(url);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  }
  function addAttachmentFile(file) {
    if (!file) return Promise.resolve();
    if (attachments.length >= LIMITS.maxFiles) { toast('附件数量已达上限（' + LIMITS.maxFiles + ' 个）', 'err'); return Promise.resolve(); }
    var total = attachments.reduce(function (s, a) { return s + a.size; }, 0) + file.size;
    if (total > LIMITS.totalBytes) { toast('附件总大小超过 ' + fmtBytes(LIMITS.totalBytes) + ' 上限', 'err'); return Promise.resolve(); }

    var name = sanitizeFileName(file.name);
    var ext = extOf(name);
    if (BLOCKED_EXTS.indexOf(ext) >= 0) { toast('不允许上传可执行文件：' + name, 'err'); return Promise.resolve(); }
    var rule = null;
    for (var i = 0; i < FILE_KINDS.length; i++) {
      if (FILE_KINDS[i].exts.indexOf(ext) >= 0) { rule = FILE_KINDS[i]; break; }
    }
    if (!rule) { toast('不支持的文件类型：' + (ext ? '.' + ext : name), 'err'); return Promise.resolve(); }
    if (file.size === 0) { toast('文件为空：' + name, 'err'); return Promise.resolve(); }
    if (file.size > rule.max) { toast('文件过大：' + name + '（上限 ' + fmtBytes(rule.max) + '）', 'err'); return Promise.resolve(); }

    var meta = {
      id: uid(8), name: name, ext: ext, size: file.size,
      mime: file.type || 'application/octet-stream', kind: rule.kind, kindLabel: rule.label,
      blob: file, thumb: null, excerpt: null, noPreview: null, _open: false
    };

    var p = Promise.resolve();
    if (rule.kind === 'image') {
      p = blobSlice(file).then(function (u8) {
        var real = sniffImageMime(u8);
        if (!real) throw new Error('fake-image');
        meta.mime = real;
        return makeThumb(file);
      }).then(function (thumb) {
        meta.thumb = thumb;
      }).catch(function (e) {
        if (e && e.message === 'fake-image') throw e;
        // makeThumb 失败不影响添加，仅无缩略图
      });
    } else if (rule.kind === 'text') {
      p = readTextHead(file, 64 * 1024).then(function (txt) {
        if (txt === null) {
          meta.kind = 'data'; meta.kindLabel = '二进制';
          meta.noPreview = '内容含二进制字节，不提供预览';
        } else {
          meta.excerpt = txt.slice(0, 32 * 1024);
        }
      });
    }
    return p.then(function () {
      attachments.push(meta);
      renderAttachments();
    }).catch(function () {
      toast('图片内容校验失败（文件头与图片格式不符）：' + name, 'err');
    });
  }
  function removeAttachment(id) {
    attachments = attachments.filter(function (a) {
      if (a.id === id && a._url) URL.revokeObjectURL(a._url);
      return a.id !== id;
    });
    renderAttachments();
  }
  function clearAttachments() {
    attachments.forEach(function (a) { if (a._url) URL.revokeObjectURL(a._url); });
    attachments = [];
    renderAttachments();
  }
  function kindIcon(a) {
    if (a.kind === 'image') return ICONS.image;
    if (a.kind === 'text') return ICONS.file;
    return ICONS.archive;
  }
  function renderAttachments() {
    var list = $('attach-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    attachments.forEach(function (a) {
      var thumb;
      if (a.kind === 'image' && a.blob) {
        if (!a._url) a._url = URL.createObjectURL(a.blob);
        thumb = el('div', { class: 'attach-thumb' }, el('img', { src: a._url, alt: '附件缩略图：' + a.name, loading: 'lazy' }));
      } else {
        thumb = el('div', { class: 'attach-thumb', html: kindIcon(a) });
      }
      var metaLine = el('div', { class: 'attach-meta' },
        el('span', { class: 'attach-tag', text: a.kindLabel }),
        fmtBytes(a.size) + ' · ' + a.mime);
      var actions = el('div', { class: 'attach-actions' });
      if (a.excerpt != null || (a.kind === 'image' && a._url) || a.noPreview) {
        var toggle = el('button', {
          class: 'icon-btn', type: 'button',
          title: a._open ? '收起预览' : '预览', 'aria-label': '切换预览',
          html: a._open ? ICONS.eyeOff : ICONS.eye,
          onclick: function () { a._open = !a._open; renderAttachments(); }
        });
        actions.appendChild(toggle);
      }
      actions.appendChild(el('button', {
        class: 'icon-btn', type: 'button', title: '移除', 'aria-label': '移除附件',
        html: ICONS.trash,
        onclick: function () { removeAttachment(a.id); }
      }));

      var card = el('li', { class: 'attach-card' },
        thumb,
        el('div', { class: 'attach-info' },
          el('div', { class: 'attach-name', text: a.name }),
          metaLine),
        actions);

      if (a._open) {
        if (a.excerpt != null) {
          card.appendChild(el('div', { class: 'attach-preview' },
            el('pre', { text: a.excerpt + (a.size > a.excerpt.length ? '\n…（已截断，完整内容见导出文件）' : '') })));
        } else if (a.kind === 'image' && a._url) {
          var imgWrap = el('div', { class: 'attach-preview', style: 'text-align:center' });
          imgWrap.appendChild(el('img', { src: a._url, alt: '附件预览：' + a.name, style: 'max-width:100%;max-height:16rem;border-radius:0.4rem' }));
          card.appendChild(imgWrap);
        } else if (a.noPreview) {
          card.appendChild(el('div', { class: 'attach-preview' }, el('pre', { text: a.noPreview })));
        }
      }
      list.appendChild(card);
    });
    var total = attachments.reduce(function (s, a) { return s + a.size; }, 0);
    var tot = $('attach-total');
    if (tot) tot.textContent = attachments.length + ' 个附件 · ' + fmtBytes(total);
  }

  /* ---------- 表单 / 草稿 ---------- */
  var formShownAt = Date.now();
  var draftSaver = debounce(function () {
    lsSet(K_DRAFT, collectForm(false));
  }, 400);
  function collectForm(forSubmit) {
    var severity = 'medium';
    var sevs = document.querySelectorAll('input[name="severity"]');
    for (var i = 0; i < sevs.length; i++) if (sevs[i].checked) severity = sevs[i].value;
    return {
      title: clean($('f-title').value, 120),
      category: $('f-category').value,
      severity: severity,
      description: clean($('f-desc').value, 4000),
      steps: clean($('f-steps').value, 3000),
      expected: clean($('f-expected').value, 500),
      actual: clean($('f-actual').value, 500),
      consent: !!$('f-consent').checked
    };
  }
  function validateForm(v) {
    if (v.title.length < 5) return { field: 'f-title', msg: '标题至少 5 个字，请概括问题' };
    if (v.description.length < 10) return { field: 'f-desc', msg: '问题描述至少 10 个字，请说明发生了什么' };
    return null;
  }
  function showFieldError(fieldId, msg) {
    var err = $(fieldId + '-err');
    var input = $(fieldId);
    if (err) { err.textContent = msg; err.hidden = false; }
    if (input) {
      input.setAttribute('aria-invalid', 'true');
      input.focus();
    }
  }
  function clearFieldErrors() {
    ['f-title', 'f-desc'].forEach(function (f) {
      var err = $(f + '-err'); if (err) { err.hidden = true; err.textContent = ''; }
      var input = $(f); if (input) input.removeAttribute('aria-invalid');
    });
    var fe = $('f-form-err'); if (fe) fe.hidden = true;
  }
  function restoreDraft() {
    var d = lsGet(K_DRAFT, null);
    if (!d || typeof d !== 'object') return;
    try {
      if (d.title) $('f-title').value = d.title;
      if (d.category && CATEGORY[d.category]) $('f-category').value = d.category;
      if (d.severity && SEVERITY[d.severity]) {
        var sevs = document.querySelectorAll('input[name="severity"]');
        for (var i = 0; i < sevs.length; i++) sevs[i].checked = sevs[i].value === d.severity;
      }
      if (d.description) $('f-desc').value = d.description;
      if (d.steps) $('f-steps').value = d.steps;
      if (d.expected) $('f-expected').value = d.expected;
      if (d.actual) $('f-actual').value = d.actual;
      $('f-consent').checked = d.consent !== false;
      var hasAny = d.title || d.description || d.steps;
      if (hasAny) toast('已恢复上次未提交的草稿（附件不保留）', 'info');
    } catch (e) { /* 忽略损坏草稿 */ }
  }
  function updateCounters() {
    var pairs = [['f-title', 'f-title-len', 120], ['f-desc', 'f-desc-len', 4000], ['f-steps', 'f-steps-len', 3000]];
    pairs.forEach(function (p) {
      var n = $(p[1]);
      if (n) n.textContent = String($(p[0]).value.length);
    });
  }
  function resetForm() {
    $('f-title').value = ''; $('f-desc').value = ''; $('f-steps').value = '';
    $('f-expected').value = ''; $('f-actual').value = '';
    $('f-category').value = 'functional';
    var sevs = document.querySelectorAll('input[name="severity"]');
    for (var i = 0; i < sevs.length; i++) sevs[i].checked = sevs[i].value === 'medium';
    clearAttachments();
    clearFieldErrors();
    updateCounters();
    formShownAt = Date.now();
  }

  /* ---------- 报告构建 / 导出 ---------- */
  function makeReportId() {
    var d = new Date();
    return 'CGDA-BUG-' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '-' + uid(4);
  }
  function buildReport(v) {
    return {
      schema: 'cgda-feedback-report/1',
      id: makeReportId(),
      createdAt: new Date().toISOString(),
      createdAtTs: Date.now(),
      title: v.title,
      category: v.category,
      categoryLabel: CATEGORY[v.category] || v.category,
      severity: v.severity,
      severityLabel: SEVERITY[v.severity] || v.severity,
      description: v.description,
      steps: v.steps,
      expected: v.expected,
      actual: v.actual,
      contact: v.consent ? {
        name: clean(identity.name, 40) || '匿名用户',
        role: ROLES[identity.role] || '其他',
        contact: clean(identity.contact, 80),
        deviceId: identity.deviceId
      } : { name: '匿名（未附带身份）', deviceId: identity.deviceId },
      env: collectEnv(),
      attachments: attachments.map(function (a) {
        return {
          id: a.id, name: a.name, ext: a.ext, size: a.size, mime: a.mime,
          kind: a.kind, kindLabel: a.kindLabel, blob: a.blob || null
        };
      }),
      client: { page: 'feedback-page/1.0' }
    };
  }
  function attachmentLine(a) {
    return '- ' + a.name + ' · ' + fmtBytes(a.size) + ' · ' + (a.kindLabel || a.kind) + (a.blobMissing ? '（二进制内容未保留，请重新提供）' : '');
  }
  function buildMarkdown(report, merged) {
    var d = new Date(report.createdAtTs || report.createdAt);
    var L = [];
    L.push('# CGDA 问题反馈 · ' + report.id);
    L.push('');
    L.push('| 项目 | 内容 |');
    L.push('| --- | --- |');
    L.push('| 提交时间 | ' + fmtDateTime(d) + ' (UTC' + offsetStr() + ') |');
    L.push('| 提交人 | ' + (report.contact.name || '匿名') + (report.contact.role ? '（' + report.contact.role + '）' : '') + ' |');
    L.push('| 设备标识 | ' + (report.contact.deviceId || '-') + ' |');
    L.push('| 联系方式 | ' + (report.contact.contact || '未提供') + ' |');
    L.push('| 问题类型 | ' + (report.categoryLabel || CATEGORY[report.category] || report.category) + ' |');
    L.push('| 严重程度 | ' + (report.severityLabel || SEVERITY[report.severity] || report.severity) + ' |');
    if (merged) {
      L.push('| 当前状态 | ' + statusLabel(merged.status) + (merged.assignee ? ' · 处理人：' + merged.assignee.name + (merged.assignee.role ? '（' + merged.assignee.role + '）' : '') : '') + ' |');
    } else {
      L.push('| 当前状态 | 已提交 |');
    }
    L.push('');
    L.push('## 标题');
    L.push('');
    L.push(report.title);
    L.push('');
    L.push('## 问题描述');
    L.push('');
    L.push(report.description);
    if (report.steps) { L.push(''); L.push('## 复现步骤'); L.push(''); L.push(report.steps); }
    if (report.expected || report.actual) {
      L.push(''); L.push('## 期望 / 实际结果'); L.push('');
      L.push('- 期望：' + (report.expected || '—'));
      L.push('- 实际：' + (report.actual || '—'));
    }
    if (report.env) {
      L.push(''); L.push('## 环境信息'); L.push('');
      Object.keys(report.env).forEach(function (k) {
        var v = report.env[k];
        if (v) L.push('- ' + k + ': ' + v);
      });
    }
    if (report.attachments && report.attachments.length) {
      L.push(''); L.push('## 附件（' + report.attachments.length + '）'); L.push('');
      report.attachments.forEach(function (a) { L.push(attachmentLine(a)); });
    }
    if (merged && merged.replies && merged.replies.length) {
      L.push(''); L.push('## 开发者回复'); L.push('');
      merged.replies.forEach(function (r) {
        L.push('**' + r.author + (r.role ? '（' + r.role + '）' : '') + '** · ' + (r.at || '') + '：');
        L.push(r.body);
        L.push('');
      });
    }
    L.push('---');
    L.push('由 CGDA 问题反馈中心生成 · ' + fmtDateTime(new Date()));
    return L.join('\n');
  }
  function blobToBase64(blob) {
    return new Promise(function (resolve, reject) {
      var fr = new FileReader();
      fr.onload = function () {
        var s = String(fr.result || '');
        resolve(s.indexOf(',') >= 0 ? s.slice(s.indexOf(',') + 1) : '');
      };
      fr.onerror = function () { reject(fr.error || new Error('read-failed')); };
      fr.readAsDataURL(blob);
    });
  }
  function buildExport(report, merged) {
    var atts = (report.attachments || []).map(function (a) {
      if (a.blob) {
        return blobToBase64(a.blob).then(function (b64) {
          return { name: a.name, mime: a.mime, size: a.size, kind: a.kind, ext: a.ext, dataBase64: b64 };
        });
      }
      return Promise.resolve({ name: a.name, mime: a.mime, size: a.size, kind: a.kind, ext: a.ext, dataBase64: null, note: a.blobMissing ? '二进制未保留' : '' });
    });
    return Promise.all(atts).then(function (attachmentData) {
      return JSON.stringify({
        schema: 'cgda-feedback-export/1',
        generatedAt: new Date().toISOString(),
        note: 'CGDA 问题反馈导出文件。请将其转交给开发者/运维；含完整报告与附件（base64）。',
        server: merged || null,
        report: stripBlobs(report),
        attachments: attachmentData
      }, null, 2);
    });
  }
  function downloadJson(report, merged) {
    buildExport(report, merged).then(function (text) {
      var blob = new Blob([text], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = report.id + '.json';
      document.body.appendChild(a);
      a.click();
      a.parentNode.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
      toast('已导出 ' + report.id + '.json', 'ok');
    }).catch(function () {
      toast('导出失败，请重试', 'err');
    });
  }

  /* ---------- 公告 / 响应数据 ---------- */
  var announcements = null;
  function safeStr(v, max) {
    return typeof v === 'string' ? clean(v, max) : '';
  }
  function validateAnnouncements(data) {
    if (!data || typeof data !== 'object') return null;
    var out = { updatedAt: safeStr(data.updatedAt, 40), maintenance: null, announcements: [], responses: [], maintainer: null };
    if (data.maintenance && typeof data.maintenance === 'object') {
      out.maintenance = {
        active: !!data.maintenance.active,
        title: safeStr(data.maintenance.title, 80) || '系统维护中',
        message: safeStr(data.maintenance.message, 500),
        window: safeStr(data.maintenance.window, 120)
      };
    }
    if (Array.isArray(data.announcements)) {
      out.announcements = data.announcements.slice(0, 20).map(function (a, i) {
        if (!a || typeof a !== 'object') return null;
        var type = ['info', 'fix', 'notice', 'security'].indexOf(a.type) >= 0 ? a.type : 'info';
        return {
          id: safeStr(a.id, 40) || ('ann-' + i),
          type: type,
          title: safeStr(a.title, 120),
          body: safeStr(a.body, 2000),
          author: safeStr(a.author, 40),
          publishedAt: safeStr(a.publishedAt, 40)
        };
      }).filter(Boolean);
    }
    if (Array.isArray(data.responses)) {
      out.responses = data.responses.slice(0, 200).map(function (r) {
        if (!r || typeof r !== 'object' || !r.reportId) return null;
        var status = STATUS[r.status] ? r.status : 'received';
        var resp = {
          reportId: safeStr(r.reportId, 60),
          status: status,
          updatedAt: safeStr(r.updatedAt, 40),
          assignee: null,
          timeline: [],
          replies: []
        };
        if (r.assignee && typeof r.assignee === 'object') {
          resp.assignee = { name: safeStr(r.assignee.name, 40), role: safeStr(r.assignee.role, 40) };
        }
        if (Array.isArray(r.timeline)) {
          resp.timeline = r.timeline.slice(0, 30).map(function (t) {
            if (!t || typeof t !== 'object') return null;
            return {
              status: STATUS[t.status] ? t.status : 'received',
              at: safeStr(t.at, 40),
              note: safeStr(t.note, 300)
            };
          }).filter(Boolean);
        }
        if (Array.isArray(r.replies)) {
          resp.replies = r.replies.slice(0, 50).map(function (q) {
            if (!q || typeof q !== 'object') return null;
            return {
              author: safeStr(q.author, 40) || '开发者',
              role: safeStr(q.role, 40),
              body: safeStr(q.body, 2000),
              at: safeStr(q.at, 40)
            };
          }).filter(Boolean);
        }
        return resp;
      }).filter(Boolean);
    }
    if (data.maintainer && typeof data.maintainer === 'object') {
      out.maintainer = {
        name: safeStr(data.maintainer.name, 60),
        email: safeStr(data.maintainer.email, 80),
        phone: safeStr(data.maintainer.phone, 40),
        im: safeStr(data.maintainer.im, 80),
        hours: safeStr(data.maintainer.hours, 60)
      };
    }
    return out;
  }
  function findResponse(reportId) {
    if (!announcements || !announcements.responses) return null;
    for (var i = 0; i < announcements.responses.length; i++) {
      if (announcements.responses[i].reportId === reportId) return announcements.responses[i];
    }
    return null;
  }
  function statusLabel(s) { return (STATUS[s] && STATUS[s].label) || s || '未知'; }

  /* ---------- 在线轨：服务端上传 / 进展查询 ---------- */
  var serverResponses = {}; // reportId -> response（renderReports 前刷新）
  function fetchWithTimeout(url, opts, ms) {
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, ms) : null;
    var merged = opts || {};
    if (ctl) merged.signal = ctl.signal;
    return fetch(url, merged).finally(function () { if (timer) clearTimeout(timer); });
  }
  function fetchServerResponse(reportId, token) {
    var url = API_BASE + '/reports/' + encodeURIComponent(reportId) +
      '/response?token=' + encodeURIComponent(token);
    return fetchWithTimeout(url, { cache: 'no-store' }, 6000)
      .then(function (r) { if (!r.ok) throw new Error('http-' + r.status); return r.json(); })
      .then(function (d) { return d && d.response ? d.response : null; })
      .catch(function () { return null; });
  }
  function uploadReportToServer(report) {
    return buildExport(report, findResponse(report.id)).then(function (text) {
      var blob = new Blob([text], { type: 'application/json' });
      var fd = new FormData();
      fd.append('file', blob, report.id + '.json');
      return fetchWithTimeout(API_BASE + '/reports', { method: 'POST', body: fd }, 90000)
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (data) {
            return { ok: r.ok, status: r.status, data: data };
          });
        });
    });
  }
  function handleUploadResult(result, report) {
    if (result.ok && result.data && result.data.token) {
      report.serverToken = result.data.token;
      storePut(report).then(function () {
        toast('已上传到服务器，工程师可直接查看（' + report.id + '）', 'ok');
        renderReports();
        updateUploadButton();
      }).catch(function () {
        toast('已上传，但访问令牌保存失败（本机存储不可用），进展查询将不可用', 'err');
      });
      return;
    }
    var detail = result.data && result.data.detail ? String(result.data.detail) : '';
    if (result.status === 409) toast(detail || '该编号已在服务器存在，无需重复上传', 'info');
    else if (result.status === 429) toast(detail || '上传过于频繁，请稍后再试', 'err');
    else if (result.status >= 500 || result.status === 0) toast('后端暂不可用，请导出 JSON 发给开发者', 'err');
    else toast(detail || '上传失败（' + result.status + '），可导出 JSON 发给开发者', 'err');
  }
  function updateUploadButton() {
    var btn = $('btn-upload-server');
    var label = $('btn-upload-server-label');
    if (!btn || !label) return;
    if (lastSubmitted && lastSubmitted.serverToken) {
      btn.disabled = true; label.textContent = '已上传服务器';
    } else if (lastHealth === 'ok') {
      btn.disabled = false; label.textContent = '上传到服务器';
    } else {
      btn.disabled = true; label.textContent = '后端不可用，请导出文件';
    }
  }

  /* ---------- 渲染：公告 / 维护横幅 / 联系渠道 ---------- */
  var ANN_TYPE_LABEL = { info: '通知', fix: '修复', notice: '维护', security: '安全' };
  function renderAnnouncements() {
    var body = $('ann-body');
    if (!body) return;
    while (body.firstChild) body.removeChild(body.firstChild);
    if (!announcements) {
      body.appendChild(el('p', { class: 'muted', text: '暂无公告（未配置或网络异常）。' }));
      return;
    }
    var list = announcements.announcements || [];
    if (!list.length) {
      body.appendChild(el('p', { class: 'muted', text: '暂无公告。' }));
    } else {
      list.forEach(function (a) {
        var head = el('div', { class: 'ann-head' },
          el('span', { class: 'ann-type ' + a.type, text: ANN_TYPE_LABEL[a.type] || '通知' }),
          el('span', { class: 'ann-title', text: a.title }));
        var item = el('div', { class: 'ann-item' },
          head,
          el('div', { class: 'ann-meta', text: [a.author, a.publishedAt].filter(Boolean).join(' · ') }));
        if (a.body) item.appendChild(el('p', { class: 'ann-body-text', text: a.body }));
        body.appendChild(item);
      });
    }
    if (announcements.updatedAt) {
      body.appendChild(el('p', { class: 'ann-updated', text: '公告更新于 ' + announcements.updatedAt }));
    }
  }
  function renderMaintenanceBanner() {
    var banner = $('maint-banner');
    if (!banner) return;
    var m = announcements && announcements.maintenance;
    if (m && m.active) {
      $('maint-title').textContent = m.title + (m.window ? '（' + m.window + '）' : '');
      $('maint-body').textContent = m.message || '前台功能可能间歇不可用，后台任务继续运行。';
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  }
  function renderContacts() {
    var list = $('contacts-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    var m = announcements && announcements.maintainer;
    if (!m) {
      list.appendChild(el('p', { class: 'hint', text: '联系方式待运维在 announcements.json 中配置。' }));
      return;
    }
    var rows = [['负责人', m.name], ['邮箱', m.email], ['电话', m.phone], ['IM', m.im], ['值守时间', m.hours]];
    rows.forEach(function (r) {
      if (!r[1]) return;
      var v = el('span', { class: 'kv-v', text: r[1] });
      if (r[1].indexOf('@') > 0) {
        var btn = el('button', { class: 'icon-btn', type: 'button', title: '复制', html: ICONS.copy, 'aria-label': '复制' + r[0] });
        btn.addEventListener('click', function () { copyAndToast(r[1], '已复制' + r[0]); });
        v.appendChild(document.createTextNode(' '));
        v.appendChild(btn);
      }
      list.appendChild(el('div', { class: 'kv' }, el('span', { class: 'kv-k', text: r[0] }), v));
    });
  }

  /* ---------- 渲染：我的反馈列表 ---------- */
  function renderReports() {
    var list = $('reports-list');
    var summary = $('reports-summary');
    var countBadge = $('reports-count');
    if (!list) return;
    storeAll().then(function (reports) {
      reports = (reports || []).filter(function (r) { return r && r.id; });
      reports.sort(function (a, b) { return (b.createdAtTs || 0) - (a.createdAtTs || 0); });
      // 在线轨：拉取已上传反馈的服务端进展（失败静默，走公告合并）
      var tokened = reports.filter(function (r) { return r.serverToken; });
      var fetches = tokened.map(function (r) { return fetchServerResponse(r.id, r.serverToken); });
      return Promise.all(fetches).then(function (results) {
        serverResponses = {};
        tokened.forEach(function (r, i) { if (results[i]) serverResponses[r.id] = results[i]; });

        while (list.firstChild) list.removeChild(list.firstChild);

        if (countBadge) {
          countBadge.textContent = String(reports.length);
          countBadge.hidden = reports.length === 0;
        }
        if (summary) {
          var synced = tokened.length;
          summary.textContent = reports.length
            ? '共 ' + reports.length + ' 条反馈（按提交时间倒序）' +
              (synced ? ' · ' + synced + ' 条已同步服务器' : '') + '。进展与追问每分钟自动同步。'
            : '尚未提交任何反馈。';
        }
        if (!reports.length) {
          var empty = el('div', { class: 'empty-state' });
          empty.innerHTML = ICONS.inbox;
          empty.appendChild(el('p', { text: '暂无反馈记录。提交的第一条反馈会出现在这里。' }));
          list.appendChild(empty);
          return;
        }
        reports.forEach(function (r) { list.appendChild(renderReportCard(r)); });
      });
    });
  }
  function renderReportCard(report) {
    // 进展合并优先级：服务端 response > announcements.json response
    var merged = serverResponses[report.id] || findResponse(report.id);
    var status = merged ? merged.status : 'submitted';
    var st = STATUS[status] || STATUS.submitted;
    var d = new Date(report.createdAtTs || report.createdAt);

    // 头部：ID + 状态徽标
    var idSpan = el('span', { class: 'report-id', text: report.id });
    var copyId = el('button', { class: 'icon-btn', type: 'button', title: '复制编号', 'aria-label': '复制反馈编号', html: ICONS.copy });
    copyId.addEventListener('click', function () { copyAndToast(report.id, '已复制反馈编号'); });
    var head = el('div', { class: 'report-head' },
      el('div', null, idSpan, document.createTextNode(' '), copyId),
      el('span', { class: 'badge tone-' + st.tone }, el('span', { class: 'dot' }), statusLabel(status)));

    // 元信息
    var meta = el('div', { class: 'report-meta' },
      el('span', { text: fmtDateTime(d) + '（' + fmtRelative(report.createdAtTs || d.getTime()) + '）' }),
      el('span', { text: CATEGORY[report.category] || report.categoryLabel || report.category }),
      el('span', { class: 'badge sev-' + report.severity, text: '严重程度：' + (SEVERITY[report.severity] || report.severityLabel || report.severity) }));
    if (merged && merged.assignee && merged.assignee.name) {
      meta.appendChild(el('span', { text: '处理人：' + merged.assignee.name + (merged.assignee.role ? '（' + merged.assignee.role + '）' : '') }));
    }

    var card = el('article', { class: 'report-card' }, head,
      el('h4', { class: 'report-title', text: report.title || '（无标题）' }),
      meta);

    if (report.serverToken) {
      var syncChip = el('span', { class: 'badge tone-ok', text: '已同步服务器' });
      meta.appendChild(syncChip);
    }

    if (report.description) {
      var desc = el('div', { class: 'report-body', text: report.description });
      var fold = el('button', {
        class: 'linklike', type: 'button', text: '展开描述',
        onclick: function () {
          var open = desc.style.display !== 'none';
          desc.style.display = open ? 'none' : 'block';
          fold.textContent = open ? '展开描述' : '收起描述';
        }
      });
      desc.style.display = 'none';
      card.appendChild(desc);
      card.appendChild(fold);
    }

    if (report.attachments && report.attachments.length) {
      card.appendChild(el('p', {
        class: 'report-attach-line',
        text: '附件 ' + report.attachments.length + ' 个：' + report.attachments.map(function (a) { return a.name; }).join('、')
      }));
    }

    // 时间线
    var tl = el('ul', { class: 'timeline' });
    var steps = [{ status: 'submitted', at: report.createdAt, note: '' }];
    if (merged && merged.timeline) {
      steps = steps.concat(merged.timeline);
    }
    steps.forEach(function (s, i) {
      var cls = 'tl-step';
      if (i === steps.length - 1 && status !== 'closed') cls += ' current';
      else cls += ' done';
      var headLine = el('div', { class: 'tl-head' },
        el('strong', { text: statusLabel(s.status) }),
        s.at ? el('span', { class: 'tl-time', text: s.at }) : null);
      var step = el('li', { class: cls }, headLine);
      if (s.note) step.appendChild(el('p', { class: 'tl-note', text: s.note }));
      tl.appendChild(step);
    });
    card.appendChild(tl);

    // 开发者追问 / 回复
    if (merged && merged.replies && merged.replies.length) {
      var replies = el('div', { class: 'replies' }, el('p', { class: 'replies-title', text: '开发者回复与追问' }));
      merged.replies.forEach(function (q) {
        replies.appendChild(el('div', { class: 'reply' },
          el('div', { class: 'reply-meta' },
            el('strong', { text: q.author + (q.role ? '（' + q.role + '）' : '') }),
            q.at ? el('span', { class: 'mono', text: q.at }) : null),
          el('div', { class: 'reply-body', text: q.body })));
      });
      card.appendChild(replies);
    }

    // 操作
    var actions = el('div', { class: 'report-actions' });
    var btnCopy = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', html: ICONS.copy + '<span>复制 Markdown</span>' });
    btnCopy.addEventListener('click', function () {
      copyAndToast(buildMarkdown(report, merged), '已复制 Markdown 报告');
    });
    var btnDl = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', html: ICONS.download + '<span>导出 JSON</span>' });
    btnDl.addEventListener('click', function () { downloadJson(report, merged); });
    actions.appendChild(btnCopy);
    actions.appendChild(btnDl);
    // 在线轨补传：未同步且后端在线时，可把历史反馈补传服务器
    if (!report.serverToken && lastHealth === 'ok') {
      var btnUp = el('button', { class: 'btn btn-ghost btn-sm', type: 'button', html: ICONS.upload + '<span>上传服务器</span>' });
      btnUp.addEventListener('click', function () {
        btnUp.disabled = true;
        uploadReportToServer(report).then(function (result) {
          handleUploadResult(result, report);
        }).catch(function () {
          toast('后端暂不可用，请导出 JSON 发给开发者', 'err');
        });
      });
      actions.appendChild(btnUp);
    }
    var btnDel = el('button', { class: 'btn btn-danger btn-sm', type: 'button', html: ICONS.trash + '<span>删除</span>' });
    var armTimer = null;
    btnDel.addEventListener('click', function () {
      if (btnDel.classList.contains('armed')) {
        storeDelete(report.id).then(function () {
          toast('已删除 ' + report.id, 'ok');
          renderReports();
        });
      } else {
        btnDel.classList.add('armed');
        btnDel.innerHTML = ICONS.alert + '<span>确认删除？</span>';
        clearTimeout(armTimer);
        armTimer = setTimeout(function () {
          btnDel.classList.remove('armed');
          btnDel.innerHTML = ICONS.trash + '<span>删除</span>';
        }, 3000);
      }
    });
    actions.appendChild(btnCopy);
    actions.appendChild(btnDl);
    actions.appendChild(btnDel);
    card.appendChild(actions);
    return card;
  }

  /* ---------- 公告拉取 / 健康检查 ---------- */
  function fetchAnnouncements(silent) {
    var loading = $('ann-loading');
    if (loading) loading.hidden = false;
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 6000) : null;
    return fetch(ANN_URL, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
      .then(function (r) {
        if (!r.ok) throw new Error('http-' + r.status);
        return r.json();
      })
      .then(function (data) {
        announcements = validateAnnouncements(data);
      })
      .catch(function () {
        if (!announcements && !silent) toast('公告加载失败，稍后自动重试', 'err');
      })
      .then(function () {
        if (timer) clearTimeout(timer);
        if (loading) loading.hidden = true;
        renderAnnouncements();
        renderMaintenanceBanner();
        renderContacts();
        renderReports();
      });
  }
  function checkHealth() {
    var pill = $('health-pill');
    var text = $('health-text');
    var detail = $('health-detail');
    var at = $('health-at');
    if (pill) { pill.dataset.state = 'checking'; }
    if (text) text.textContent = '检测后端中…';
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 4000) : null;
    var finish = function (state) {
      var changed = lastHealth !== state;
      lastHealth = state;
      if (timer) clearTimeout(timer);
      var map = {
        ok: ['ok', '后端正常', '正常（/health 可达）'],
        down: ['down', '后端异常', '不可达或返回错误']
      }[state];
      if (pill && map) pill.dataset.state = map[0];
      if (text && map) text.textContent = map[1];
      if (detail && map) detail.textContent = map[2];
      if (at) at.textContent = fmtDateTime(new Date());
      // 状态翻转时刷新上传入口与列表（在线轨按钮依赖健康态）
      if (changed) {
        updateUploadButton();
        renderReports();
      }
    };
    fetch(HEALTH_URL, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
      .then(function (r) { finish(r.ok ? 'ok' : 'down'); })
      .catch(function () { finish('down'); });
  }

  /* ---------- 选项卡 ---------- */
  function switchTab(name) {
    var isSubmit = name === 'submit';
    $('tab-submit').setAttribute('aria-selected', String(isSubmit));
    $('tab-reports').setAttribute('aria-selected', String(!isSubmit));
    $('panel-submit').hidden = !isSubmit;
    $('panel-reports').hidden = isSubmit;
    if (!isSubmit) renderReports();
  }

  /* ---------- 提交流程 ---------- */
  var lastSubmitted = null;
  function showSuccess(report) {
    $('fb-form').hidden = true;
    var sp = $('success-panel');
    sp.hidden = false;
    $('success-id').textContent = report.id;
    var d = new Date(report.createdAtTs);
    $('success-time').textContent = fmtDateTime(d) + ' (UTC' + offsetStr() + ')';
    lastSubmitted = report;
    updateUploadButton();
    sp.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function hideSuccess() {
    $('success-panel').hidden = true;
    $('fb-form').hidden = false;
    lastSubmitted = null;
  }

  function initFormEvents() {
    var form = $('fb-form');
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      clearFieldErrors();
      if (clean($('hp-website').value, 100)) {
        var fe = $('f-form-err'); fe.textContent = '检测到异常提交，请正常填写表单。'; fe.hidden = false;
        return;
      }
      if (Date.now() - formShownAt < 2000) {
        var fe2 = $('f-form-err'); fe2.textContent = '页面刚加载就提交了，请检查内容后重试。'; fe2.hidden = false;
        return;
      }
      var v = collectForm(true);
      var err = validateForm(v);
      if (err) { showFieldError(err.field, err.msg); return; }
      var rl = checkRate();
      if (!rl.ok) {
        var fe3 = $('f-form-err'); fe3.textContent = rl.msg; fe3.hidden = false;
        return;
      }
      var report = buildReport(v);
      var submitBtn = $('btn-submit');
      submitBtn.disabled = true;
      storePut(report).then(function (mode) {
        recordSubmit();
        localStorage.removeItem(K_DRAFT);
        resetForm();
        showSuccess(report);
        renderReports();
        if (mode === 'ls') {
          toast('已保存（浏览器存储受限，附件二进制未保留，请立即导出 JSON）', 'err');
        } else {
          toast('反馈已记录：' + report.id, 'ok');
        }
      }).catch(function () {
        toast('本地保存失败（存储不可用），请截图保存当前内容', 'err');
      }).then(function () {
        submitBtn.disabled = false;
      });
    });

    // 字符计数 + 草稿自动保存
    ['f-title', 'f-desc', 'f-steps', 'f-expected', 'f-actual', 'f-category'].forEach(function (id) {
      var n = $(id);
      if (n) n.addEventListener('input', function () { updateCounters(); draftSaver(); });
    });
    var consent = $('f-consent');
    if (consent) consent.addEventListener('change', draftSaver);
    var sevs = document.querySelectorAll('input[name="severity"]');
    for (var i = 0; i < sevs.length; i++) sevs[i].addEventListener('change', draftSaver);

    $('btn-clear-draft').addEventListener('click', function () {
      localStorage.removeItem(K_DRAFT);
      resetForm();
      hideSuccess();
      toast('表单已清空', 'ok');
    });

    // 成功面板动作
    $('btn-copy-md').addEventListener('click', function () {
      if (lastSubmitted) copyAndToast(buildMarkdown(lastSubmitted, findResponse(lastSubmitted.id)), '已复制 Markdown 报告');
    });
    $('btn-download-json').addEventListener('click', function () {
      if (lastSubmitted) downloadJson(lastSubmitted, findResponse(lastSubmitted.id));
    });
    $('btn-upload-server').addEventListener('click', function () {
      if (!lastSubmitted || lastSubmitted.serverToken) return;
      var btn = $('btn-upload-server');
      var label = $('btn-upload-server-label');
      btn.disabled = true;
      label.textContent = '上传中…';
      uploadReportToServer(lastSubmitted).then(function (result) {
        return handleUploadResult(result, lastSubmitted);
      }).catch(function () {
        toast('后端暂不可用，请导出 JSON 发给开发者', 'err');
      }).then(function () {
        if (!(lastSubmitted && lastSubmitted.serverToken)) updateUploadButton();
      });
    });
    $('btn-new-report').addEventListener('click', hideSuccess);
    $('btn-goto-reports').addEventListener('click', function () { switchTab('reports'); });
  }

  /* ---------- 附件区事件 ---------- */
  function initAttachmentEvents() {
    var dz = $('dropzone');
    var fi = $('file-input');
    dz.addEventListener('click', function () { fi.click(); });
    dz.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); fi.click(); }
    });
    ['dragenter', 'dragover'].forEach(function (t) {
      dz.addEventListener(t, function (ev) { ev.preventDefault(); dz.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(function (t) {
      dz.addEventListener(t, function (ev) { ev.preventDefault(); dz.classList.remove('dragover'); });
    });
    dz.addEventListener('drop', function (ev) {
      var files = ev.dataTransfer && ev.dataTransfer.files;
      handleFileList(files);
    });
    fi.addEventListener('change', function () {
      handleFileList(fi.files);
      fi.value = '';
    });
    $('btn-paste-shot').addEventListener('click', function () {
      if (!(navigator.clipboard && navigator.clipboard.read)) {
        toast('当前环境不支持按钮读取剪贴板，请在页面空白处直接 Ctrl+V', 'info');
        return;
      }
      navigator.clipboard.read().then(function (items) {
        var chain = Promise.resolve();
        var found = 0;
        items.forEach(function (it) {
          var type = (it.types || []).filter(function (t) { return t.indexOf('image/') === 0; })[0];
          if (type) {
            found++;
            chain = chain.then(function () {
              return it.getType(type).then(function (blob) {
                var d = new Date();
                var name = '剪贴板截图-' + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()) + '.png';
                return addAttachmentFile(new File([blob], name, { type: type }));
              });
            });
          }
        });
        return chain.then(function () {
          if (!found) toast('剪贴板中没有图片', 'info');
          else toast('已添加 ' + found + ' 张剪贴板截图', 'ok');
        });
      }).catch(function () {
        toast('无法读取剪贴板（需要授权），请直接 Ctrl+V', 'info');
      });
    });

    // 全局粘贴：输入框外粘贴图片 → 作为附件
    document.addEventListener('paste', function (ev) {
      var t = ev.target;
      var tag = t && t.tagName;
      var inField = tag === 'INPUT' || tag === 'TEXTAREA' || (t && t.isContentEditable);
      if (inField) return;
      var items = ev.clipboardData && ev.clipboardData.items;
      if (!items) return;
      var imgs = [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].kind === 'file') {
          var f = items[i].getAsFile();
          if (f && f.type && f.type.indexOf('image/') === 0) imgs.push(f);
        }
      }
      if (imgs.length) {
        ev.preventDefault();
        var chain = Promise.resolve();
        imgs.forEach(function (f) {
          var d = new Date();
          var name = '剪贴板截图-' + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds()) + '.png';
          chain = chain.then(function () { return addAttachmentFile(new File([f], name, { type: f.type })); });
        });
        chain.then(function () { toast('已添加 ' + imgs.length + ' 张剪贴板截图', 'ok'); });
      }
    });
  }
  function handleFileList(files) {
    if (!files || !files.length) return;
    var arr = Array.prototype.slice.call(files, 0, LIMITS.maxFiles + 1);
    var chain = Promise.resolve();
    arr.forEach(function (f) { chain = chain.then(function () { return addAttachmentFile(f); }); });
  }

  /* ---------- 侧栏 / 选项卡 / 轮询事件 ---------- */
  function initMiscEvents() {
    // 身份
    var nameI = $('i-name'), roleI = $('i-role'), contactI = $('i-contact');
    nameI.value = identity.name || '';
    roleI.value = identity.role || 'researcher';
    contactI.value = identity.contact || '';
    // 首次访问：用字段默认值同步 identity 与身份条（避免 debounce 延迟造成首帧不一致）
    identity.name = clean(nameI.value, 40);
    identity.role = roleI.value;
    identity.contact = clean(contactI.value, 80);
    saveIdentity();
    updateIdentityStrip();
    var identitySaver = debounce(function () {
      identity.name = clean(nameI.value, 40);
      identity.role = roleI.value;
      identity.contact = clean(contactI.value, 80);
      saveIdentity();
      updateIdentityStrip();
    }, 300);
    [nameI, roleI, contactI].forEach(function (n) { n.addEventListener('input', identitySaver); n.addEventListener('change', identitySaver); });
    $('btn-copy-device').addEventListener('click', function () { copyAndToast(identity.deviceId, '已复制设备标识'); });

    // 选项卡
    $('tab-submit').addEventListener('click', function () { switchTab('submit'); });
    $('tab-reports').addEventListener('click', function () { switchTab('reports'); });

    // 我的反馈工具条
    $('btn-refresh-status').addEventListener('click', function () {
      fetchAnnouncements(true).then(function () { toast('已刷新进展与公告', 'ok'); });
    });
    var clearBtn = $('btn-clear-all');
    var clearTimer = null;
    clearBtn.addEventListener('click', function () {
      if (clearBtn.classList.contains('armed')) {
        storeClear().then(function () {
          renderReports();
          toast('已清空全部本地反馈', 'ok');
          clearBtn.classList.remove('armed');
          clearBtn.textContent = '清空全部';
        });
      } else {
        clearBtn.classList.add('armed');
        clearBtn.textContent = '确认清空？';
        clearTimeout(clearTimer);
        clearTimer = setTimeout(function () {
          clearBtn.classList.remove('armed');
          clearBtn.textContent = '清空全部';
        }, 3000);
      }
    });

    // 健康
    $('btn-health-now').addEventListener('click', checkHealth);

    // 时钟
    var clock = $('clock');
    var footerTime = $('footer-time');
    function tick() {
      var now = new Date();
      if (clock) clock.textContent = fmtDateTime(now);
      if (footerTime) footerTime.textContent = '页面打开于 ' + fmtDateTime(bootTime) + ' · 当前 ' + fmtDateTime(now);
    }
    tick();
    setInterval(tick, 1000);

    // 轮询（仅页面可见时）
    setInterval(function () {
      if (!document.hidden) fetchAnnouncements(true);
    }, ANN_POLL_MS);
    setInterval(function () {
      if (!document.hidden) checkHealth();
    }, HEALTH_POLL_MS);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { fetchAnnouncements(true); checkHealth(); }
    });
  }

  /* ---------- 启动 ---------- */
  var bootTime = new Date();
  function init() {
    toastStack = $('toast-stack');
    updateIdentityStrip();
    restoreDraft();
    updateCounters();
    initFormEvents();
    initAttachmentEvents();
    initMiscEvents();
    renderAttachments();
    checkHealth();
    fetchAnnouncements(false).then(function () { renderReports(); });
    // 提示粘贴能力
    if (!navigator.clipboard || !navigator.clipboard.read) {
      var hint = document.querySelector('.dropzone .hint');
      if (hint) hint.textContent = '支持直接 Ctrl+V 粘贴截图 · 单图 ≤10MB · 文本 ≤2MB · 数据 ≤25MB · 最多 10 个';
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
