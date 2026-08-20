/* ============================================================
   CGDA 反馈处理台 · console.js（工程师端）
   导入用户导出的反馈 JSON（拖放 / 选择 / 粘贴文本）→ 本机 IndexedDB 留存 →
   查看报告详情（含 base64 附件的图片预览 / 文本预览 / 下载）→
   编排处理进展与回复 → 生成 responses JSON 粘贴回 announcements.json 发布。

   安全：所有数据一律 textContent 渲染（innerHTML 仅常量图标）；
   导入数据字段级净化 + 长度上限；数据仅存本机。
   ============================================================ */
'use strict';

(function () {
  /* ---------- 常量 ---------- */
  var ANN_URL = 'data/announcements.json';
  var HEALTH_URL = '/health';
  var ANN_POLL_MS = 60 * 1000;
  var HEALTH_POLL_MS = 30 * 1000;
  var MAX_IMPORT_TEXT = 80 * 1024 * 1024; // 单次导入 JSON 文本上限

  var STATUS = {
    submitted: { label: '已提交', tone: 'info' },
    received: { label: '已受理', tone: 'info' },
    in_progress: { label: '处理中', tone: 'warn' },
    needs_info: { label: '待补充信息', tone: 'warn' },
    fixed: { label: '已修复', tone: 'ok' },
    closed: { label: '已关闭', tone: 'muted' },
    rejected: { label: '不予处理', tone: 'danger' }
  };
  var COMPOSER_STATUS = ['received', 'in_progress', 'needs_info', 'fixed', 'closed', 'rejected'];
  var SEVERITY = { low: '低', medium: '中', high: '高', critical: '紧急' };
  var CATEGORY = {
    functional: '功能缺陷', data: '数据显示异常', workflow: '工作流问题', performance: '性能问题',
    ui: '界面与交互', ingest: '数据接入', deploy: '部署与运维', security: '安全相关', other: '其他'
  };

  /* ---------- 图标 ---------- */
  function svg(paths) {
    return '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths + '</svg>';
  }
  var ICONS = {
    copy: svg('<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'),
    download: svg('<path d="M21 15v3.5A2.5 2.5 0 0 1 18.5 21h-13A2.5 2.5 0 0 1 3 18.5V15M12 3v13M7.5 11.5 12 16l4.5-4.5"/>'),
    trash: svg('<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6"/>'),
    eye: svg('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
    eyeOff: svg('<path d="M17.94 17.94A10.5 10.5 0 0 1 12 19c-6.5 0-10-7-10-7a18.5 18.5 0 0 1 5.06-5.94M9.9 4.24A10.5 10.5 0 0 1 12 4c6.5 0 10 7 10 7a18.5 18.5 0 0 1-3.16 4.19M14.12 14.12a3 3 0 1 1-4.24-4.24M3 3l18 18"/>'),
    check: svg('<path d="M4.5 12.5 10 18 19.5 6.5"/>'),
    alert: svg('<path d="M12 8v5M12 16.5h.01"/><path d="M10.3 3.6 1.9 18a2 2 0 0 0 1.7 3h16.8a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z"/>'),
    info: svg('<circle cx="12" cy="12" r="9"/><path d="M12 8h.01M12 11v5"/>'),
    inbox: svg('<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1Z"/>'),
    chat: svg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10Z"/>')
  };

  /* ---------- 工具 ---------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v == null) return;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k === 'html') n.innerHTML = v; // 仅限常量图标
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
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1024 / 1024).toFixed(2) + ' MB';
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function fmtDateTime(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }
  function fmtShort(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  function clean(s, max) {
    return String(s == null ? '' : s)
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '')
      .trim()
      .slice(0, max);
  }
  function safeStr(v, max) { return typeof v === 'string' ? clean(v, max) : ''; }
  function safeNum(v) { return typeof v === 'number' && isFinite(v) ? v : null; }
  function toast(msg, type) {
    var stack = $('toast-stack');
    if (!stack) return;
    var iconHtml = type === 'ok' ? ICONS.check : (type === 'err' ? ICONS.alert : ICONS.info);
    var t = el('div', { class: 'toast toast-' + (type || 'info'), html: iconHtml }, el('span', { text: msg }));
    stack.appendChild(t);
    setTimeout(function () {
      t.classList.add('out');
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 320);
    }, 3600);
  }
  function copyText(text) {
    return new Promise(function (resolve) {
      if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { resolve(true); }, function () { resolve(legacyCopy(text)); });
      } else resolve(legacyCopy(text));
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
  function b64ToBlob(b64, mime) {
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: mime || 'application/octet-stream' });
  }
  function downloadBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.parentNode.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
  }
  function statusLabel(s) { return (STATUS[s] && STATUS[s].label) || s || '未知'; }

  /* ---------- IndexedDB ---------- */
  function idbOpen() {
    return new Promise(function (resolve, reject) {
      if (!('indexedDB' in window)) return reject(new Error('no-idb'));
      var req = indexedDB.open('cgda-feedback-console', 1);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains('reports')) db.createObjectStore('reports', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('responses')) db.createObjectStore('responses', { keyPath: 'reportId' });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error || new Error('idb-open-failed')); };
    });
  }
  function idbTx(store, mode, fn) {
    return idbOpen().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(store, mode);
        var req = fn(tx.objectStore(store));
        var result;
        if (req) req.onsuccess = function () { result = req.result; };
        tx.oncomplete = function () { resolve(result); };
        tx.onerror = function () { reject(tx.error || new Error('idb-tx-failed')); };
        tx.onabort = function () { reject(tx.error || new Error('idb-abort')); };
      });
    });
  }
  function dbPutReport(rec) { return idbTx('reports', 'readwrite', function (s) { return s.put(rec); }); }
  function dbAllReports() { return idbTx('reports', 'readonly', function (s) { return s.getAll(); }).then(function (r) { return r || []; }); }
  function dbDeleteReport(id) { return idbTx('reports', 'readwrite', function (s) { return s.delete(id); }); }
  function dbClearReports() { return idbTx('reports', 'readwrite', function (s) { return s.clear(); }); }
  function dbPutResponse(resp) { return idbTx('responses', 'readwrite', function (s) { return s.put(resp); }); }
  function dbAllResponses() { return idbTx('responses', 'readonly', function (s) { return s.getAll(); }).then(function (r) { return r || []; }); }
  function dbDeleteResponse(id) { return idbTx('responses', 'readwrite', function (s) { return s.delete(id); }); }
  function dbClearResponses() { return idbTx('responses', 'readwrite', function (s) { return s.clear(); }); }

  /* ---------- 导入解析 ---------- */
  function normalizeAttachment(a) {
    if (!a || typeof a !== 'object') return null;
    var b64 = typeof a.dataBase64 === 'string' && a.dataBase64.length > 0 && a.dataBase64.length < 45 * 1024 * 1024 ? a.dataBase64 : null;
    return {
      name: safeStr(a.name, 120) || 'unnamed',
      mime: safeStr(a.mime, 80) || 'application/octet-stream',
      size: safeNum(a.size) || 0,
      kind: ['image', 'text', 'data'].indexOf(a.kind) >= 0 ? a.kind : 'data',
      kindLabel: safeStr(a.kindLabel, 20) || '数据',
      ext: safeStr(a.ext, 12),
      dataBase64: b64,
      note: safeStr(a.note, 80)
    };
  }
  function normalizeReport(obj) {
    // 支持两种来源：完整导出文件 {schema:'cgda-feedback-export/1', report, attachments} 或单个 report 对象
    var raw = null, topAtts = null, server = null;
    if (obj && typeof obj === 'object' && obj.schema === 'cgda-feedback-export/1') {
      raw = obj.report;
      topAtts = Array.isArray(obj.attachments) ? obj.attachments : [];
      server = obj.server && typeof obj.server === 'object' ? obj.server : null;
    } else if (obj && typeof obj === 'object' && typeof obj.id === 'string' && obj.id.indexOf('CGDA-BUG-') === 0) {
      raw = obj;
      topAtts = Array.isArray(obj.attachments) ? obj.attachments : [];
    }
    if (!raw || typeof raw !== 'object') return null;

    var id = safeStr(raw.id, 64);
    if (!/^CGDA-BUG-[A-Za-z0-9-]{3,60}$/.test(id)) return null;

    var createdAtTs = safeNum(raw.createdAtTs);
    if (!createdAtTs) {
      var t = Date.parse(safeStr(raw.createdAt, 40));
      createdAtTs = isFinite(t) ? t : Date.now();
    }
    var contact = (raw.contact && typeof raw.contact === 'object') ? raw.contact : {};
    var envIn = (raw.env && typeof raw.env === 'object') ? raw.env : {};
    var env = {};
    Object.keys(envIn).slice(0, 30).forEach(function (k) {
      var v = envIn[k];
      if (v == null) return;
      env[safeStr(k, 30)] = safeStr(String(v), 200);
    });

    // 合并附件：report.attachments 元数据 + 顶层 attachments（含 base64），按索引对齐，名称不一致时按名称回退
    var metaAtts = Array.isArray(raw.attachments) ? raw.attachments.slice(0, 20) : [];
    var atts = [];
    for (var i = 0; i < metaAtts.length; i++) {
      var meta = normalizeAttachment(metaAtts[i]);
      if (!meta) continue;
      var top = null;
      if (i < topAtts.length && safeStr(topAtts[i] && topAtts[i].name, 120) === meta.name) {
        top = topAtts[i]; topAtts[i]._used = true;
      } else {
        for (var j = 0; j < topAtts.length; j++) {
          if (topAtts[j] && !topAtts[j]._used && safeStr(topAtts[j].name, 120) === meta.name) {
            top = topAtts[j]; topAtts[j]._used = true; break;
          }
        }
      }
      if (top && typeof top.dataBase64 === 'string' && top.dataBase64.length < 45 * 1024 * 1024) {
        meta.dataBase64 = top.dataBase64;
        if (safeStr(top.mime, 80)) meta.mime = safeStr(top.mime, 80);
      }
      atts.push(meta);
    }
    // 顶层有但元数据缺失的附件（少见）也保留
    for (var k2 = 0; k2 < topAtts.length; k2++) {
      if (topAtts[k2] && !topAtts[k2]._used && atts.length >= 20) break;
      if (topAtts[k2] && !topAtts[k2]._used) {
        var extra = normalizeAttachment(topAtts[k2]);
        if (extra) atts.push(extra);
      }
    }

    return {
      id: id,
      title: safeStr(raw.title, 200) || '（无标题）',
      description: safeStr(raw.description, 8000),
      steps: safeStr(raw.steps, 6000),
      expected: safeStr(raw.expected, 1000),
      actual: safeStr(raw.actual, 1000),
      category: safeStr(raw.category, 30),
      categoryLabel: safeStr(raw.categoryLabel, 20) || CATEGORY[safeStr(raw.category, 30)] || '其他',
      severity: ['low', 'medium', 'high', 'critical'].indexOf(raw.severity) >= 0 ? raw.severity : 'medium',
      severityLabel: safeStr(raw.severityLabel, 10) || SEVERITY[['low', 'medium', 'high', 'critical'].indexOf(raw.severity) >= 0 ? raw.severity : 'medium'],
      createdAt: safeStr(raw.createdAt, 40),
      createdAtTs: createdAtTs,
      contact: {
        name: safeStr(contact.name, 40) || '匿名',
        role: safeStr(contact.role, 40),
        contact: safeStr(contact.contact, 80),
        deviceId: safeStr(contact.deviceId, 20)
      },
      env: env,
      attachments: atts,
      exportedServer: server,
      importedAt: new Date().toISOString()
    };
  }
  function importJsonText(text, sourceLabel) {
    if (typeof text !== 'string' || !text.trim()) { toast('内容为空，未导入', 'err'); return Promise.resolve(false); }
    if (text.length > MAX_IMPORT_TEXT) { toast('文件过大（超过 80MB），拒绝导入', 'err'); return Promise.resolve(false); }
    var data;
    try { data = JSON.parse(text); } catch (e) { toast('JSON 解析失败：' + (sourceLabel || '内容') + ' 不是合法 JSON', 'err'); return Promise.resolve(false); }
    var list = Array.isArray(data) ? data : [data];
    var okCount = 0, failCount = 0;
    var chain = Promise.resolve();
    list.slice(0, 20).forEach(function (item) {
      chain = chain.then(function () {
        var rec = normalizeReport(item);
        if (!rec) { failCount++; return; }
        return dbPutReport(rec).then(function () { okCount++; });
      });
    });
    return chain.then(function () {
      renderAll();
      if (okCount) toast('已导入 ' + okCount + ' 条反馈' + (failCount ? '，' + failCount + ' 条格式无效被跳过' : ''), 'ok');
      else toast('未识别到有效反馈数据（需要导出文件或 CGDA-BUG-* report 对象）', 'err');
      return okCount > 0;
    });
  }

  /* ---------- 公告（已发布状态） ---------- */
  var published = {}; // reportId -> response
  function fetchAnnouncements(silent) {
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 6000) : null;
    return fetch(ANN_URL, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error('http-' + r.status); return r.json(); })
      .then(function (data) {
        published = {};
        if (data && Array.isArray(data.responses)) {
          data.responses.forEach(function (r) {
            if (r && typeof r === 'object' && typeof r.reportId === 'string' && STATUS[r.status]) {
              published[r.reportId] = {
                reportId: safeStr(r.reportId, 64),
                status: STATUS[r.status] ? r.status : 'received',
                updatedAt: safeStr(r.updatedAt, 40),
                assignee: (r.assignee && typeof r.assignee === 'object') ? {
                  name: safeStr(r.assignee.name, 40), role: safeStr(r.assignee.role, 40)
                } : null,
                timeline: Array.isArray(r.timeline) ? r.timeline.slice(0, 30).map(function (t) {
                  return t && typeof t === 'object' ? {
                    status: STATUS[t.status] ? t.status : 'received',
                    at: safeStr(t.at, 40), note: safeStr(t.note, 300)
                  } : null;
                }).filter(Boolean) : [],
                replies: Array.isArray(r.replies) ? r.replies.slice(0, 50).map(function (q) {
                  return q && typeof q === 'object' ? {
                    author: safeStr(q.author, 40) || '开发者',
                    role: safeStr(q.role, 40), body: safeStr(q.body, 2000), at: safeStr(q.at, 40)
                  } : null;
                }).filter(Boolean) : []
              };
            }
          });
        }
      })
      .catch(function () {
        if (!silent) toast('公告拉取失败，已发布状态可能不准确', 'err');
      })
      .then(function () {
        if (timer) clearTimeout(timer);
        renderAll();
      });
  }

  /* ---------- 渲染 ---------- */
  var openCards = {}; // id -> true
  var pendingResponses = {}; // reportId -> response（内存缓存，render 时刷新）
  var currentFilter = { q: '', status: 'all' };

  function effectiveStatus(id) {
    if (published[id]) return published[id].status;
    if (pendingResponses[id]) return pendingResponses[id].status;
    return 'submitted';
  }
  function renderAll() {
    Promise.all([dbAllReports(), dbAllResponses()]).then(function (res) {
      var reports = res[0], responses = res[1];
      pendingResponses = {};
      responses.forEach(function (r) { if (r && r.reportId) pendingResponses[r.reportId] = r; });
      reports.sort(function (a, b) { return (b.createdAtTs || 0) - (a.createdAtTs || 0); });
      renderList(reports);
      renderPending(responses);
      var sum = $('import-summary');
      if (sum) sum.textContent = reports.length
        ? '已导入 ' + reports.length + ' 条反馈（本机留存）' + (responses.length ? ' · ' + responses.length + ' 条待发布回复' : '')
        : '尚未导入任何反馈。';
    });
  }
  function matchFilter(r) {
    if (currentFilter.status !== 'all' && effectiveStatus(r.id) !== currentFilter.status) return false;
    var q = currentFilter.q;
    if (!q) return true;
    var hay = [r.id, r.title, r.description, r.contact && r.contact.name, r.contact && r.contact.contact]
      .map(function (s) { return String(s || '').toLowerCase(); }).join(' ');
    return hay.indexOf(q) >= 0;
  }
  function renderList(reports) {
    var list = $('reports-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    var shown = reports.filter(matchFilter);
    if (!shown.length) {
      var empty = el('div', { class: 'empty-state' });
      empty.innerHTML = ICONS.inbox;
      empty.appendChild(el('p', {
        text: reports.length
          ? '没有符合当前筛选条件的反馈。'
          : '暂无反馈记录。让用户在 /feedback/ 页「导出完整 JSON」发给你，再拖入上方导入区。'
      }));
      list.appendChild(empty);
      return;
    }
    shown.forEach(function (r) { list.appendChild(renderCard(r)); });
  }

  function renderCard(r) {
    var merged = published[r.id] || null;
    var pending = pendingResponses[r.id] || null;
    var status = effectiveStatus(r.id);
    var st = STATUS[status] || STATUS.submitted;
    var d = new Date(r.createdAtTs);

    // 头部
    var idSpan = el('span', { class: 'report-id', text: r.id });
    var copyId = el('button', { class: 'icon-btn', type: 'button', title: '复制编号', 'aria-label': '复制反馈编号', html: ICONS.copy });
    copyId.addEventListener('click', function (ev) { ev.stopPropagation(); copyAndToast(r.id, '已复制反馈编号'); });
    var chips = el('span', { class: 'card-id-row' }, idSpan, copyId);
    if (merged) chips.appendChild(el('span', { class: 'published-chip', text: '已发布' }));
    else if (pending) chips.appendChild(el('span', { class: 'pending-chip', text: '待发布' }));

    var right = el('span', { class: 'badge tone-' + st.tone }, el('span', { class: 'dot' }), statusLabel(status));
    var head = el('div', { class: 'console-card-head', role: 'button', tabindex: '0' },
      el('div', null, chips,
        el('h3', { class: 'card-title-line', text: r.title }),
        el('div', { class: 'card-meta-line' },
          el('span', { text: (r.contact.name || '匿名') + (r.contact.role ? '（' + r.contact.role + '）' : '') + ' · ' + fmtDateTime(d) }),
          el('span', { text: r.categoryLabel }),
          el('span', { class: 'badge sev-' + r.severity, text: SEVERITY[r.severity] || r.severityLabel }),
          r.attachments && r.attachments.length ? el('span', { text: '附件 ' + r.attachments.length + ' 个' }) : null)),
      right);
    function toggleCard() { openCards[r.id] = !openCards[r.id]; renderAll(); }
    head.addEventListener('click', toggleCard);
    head.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggleCard(); }
    });

    var card = el('article', { class: 'console-card' + (openCards[r.id] ? ' open' : '') }, head);
    if (openCards[r.id]) card.appendChild(renderCardBody(r, merged, pending));
    return card;
  }

  function section(title, bodyEl) {
    return el('div', { class: 'detail-section' }, el('h4', { text: title }), bodyEl);
  }
  function renderCardBody(r, merged, pending) {
    var body = el('div', { class: 'console-card-body' });

    if (r.description) body.appendChild(section('问题描述', el('p', { class: 'detail-text', text: r.description })));
    if (r.steps) body.appendChild(section('复现步骤', el('p', { class: 'detail-text', text: r.steps })));
    if (r.expected || r.actual) {
      body.appendChild(section('期望 / 实际结果', el('p', { class: 'detail-text', text: '期望：' + (r.expected || '—') + '\n实际：' + (r.actual || '—') })));
    }

    // 提交人
    var contactRows = el('div', { class: 'env-grid' });
    [['提交人', r.contact.name], ['角色', r.contact.role], ['联系方式', r.contact.contact], ['设备标识', r.contact.deviceId], ['提交时间', fmtDateTime(new Date(r.createdAtTs))]]
      .forEach(function (row) {
        if (row[1]) contactRows.appendChild(el('div', { class: 'kv' }, el('span', { class: 'kv-k', text: row[0] }), el('span', { class: 'kv-v', text: row[1] })));
      });
    body.appendChild(section('提交人信息', contactRows));

    // 环境
    if (r.env && Object.keys(r.env).length) {
      var envGrid = el('div', { class: 'env-grid' });
      Object.keys(r.env).forEach(function (k) {
        envGrid.appendChild(el('div', { class: 'kv' }, el('span', { class: 'kv-k', text: k }), el('span', { class: 'kv-v', text: r.env[k] })));
      });
      body.appendChild(section('环境信息', envGrid));
    }

    // 附件
    if (r.attachments && r.attachments.length) {
      body.appendChild(section('附件（' + r.attachments.length + '）', renderAttachments(r.attachments)));
    }

    // 已发布回复
    if (merged) {
      var pub = el('div', { class: 'published-block' });
      if (merged.assignee && merged.assignee.name) {
        pub.appendChild(el('p', { class: 'replies-title', text: '已发布状态：' + statusLabel(merged.status) + ' · 处理人：' + merged.assignee.name + (merged.assignee.role ? '（' + merged.assignee.role + '）' : '') + (merged.updatedAt ? ' · 更新于 ' + merged.updatedAt : '') }));
      }
      if (merged.replies && merged.replies.length) {
        var replies = el('div', { class: 'replies' }, el('p', { class: 'replies-title', text: '已发布的回复与追问' }));
        merged.replies.forEach(function (q) {
          replies.appendChild(el('div', { class: 'reply' },
            el('div', { class: 'reply-meta' },
              el('strong', { text: q.author + (q.role ? '（' + q.role + '）' : '') }),
              q.at ? el('span', { class: 'mono', text: q.at }) : null),
            el('div', { class: 'reply-body', text: q.body })));
        });
        pub.appendChild(replies);
      }
      if (pub.childNodes.length) body.appendChild(pub);
    }

    // 回复编排器
    body.appendChild(renderComposer(r, merged, pending));
    return body;
  }

  function renderAttachments(atts) {
    var grid = el('div', { class: 'attach-grid' });
    atts.forEach(function (a) {
      var row = el('div', { class: 'attach-row' });
      if (a.kind === 'image' && a.dataBase64) {
        row.appendChild(el('img', { src: 'data:' + a.mime + ';base64,' + a.dataBase64, alt: '附件缩略图：' + a.name, loading: 'lazy' }));
      } else {
        var ic = a.kind === 'image' ? ICONS.info : (a.kind === 'text' ? ICONS.copy : ICONS.download);
        row.appendChild(el('span', { class: 'attach-thumb', html: ic }));
      }
      row.appendChild(el('div', { class: 'attach-info' },
        el('div', { class: 'attach-name', text: a.name }),
        el('div', { class: 'attach-meta', text: (a.kindLabel || a.kind) + ' · ' + fmtBytes(a.size) + ' · ' + a.mime + (a.dataBase64 ? '' : (a.note ? ' · ' + a.note : ' · 未含二进制内容')) })));
      var btns = el('div', { class: 'attach-actions' });
      if (a.dataBase64 && a.kind === 'text') {
        var pre = null;
        var toggle = el('button', {
          class: 'icon-btn', type: 'button', title: '预览文本', 'aria-label': '预览文本', html: ICONS.eye,
          onclick: function () {
            if (pre && pre.parentNode) { pre.parentNode.removeChild(pre); pre = null; return; }
            try {
              var blob = b64ToBlob(a.dataBase64, a.mime);
              blob.arrayBuffer().then(function (ab) {
                var txt = new TextDecoder('utf-8', { fatal: false }).decode(ab.slice(0, 32 * 1024));
                pre = el('div', { class: 'attach-text-preview' }, el('pre', { text: txt + (a.size > 32 * 1024 ? '\n…（已截断）' : '') }));
                row.appendChild(pre);
              });
            } catch (e) { toast('文本解码失败', 'err'); }
          }
        });
        btns.appendChild(toggle);
      }
      if (a.dataBase64 && a.kind === 'image') {
        var full = null;
        var zoom = el('button', {
          class: 'icon-btn', type: 'button', title: '查看大图', 'aria-label': '查看大图', html: ICONS.eye,
          onclick: function () {
            if (full && full.parentNode) { full.parentNode.removeChild(full); full = null; return; }
            full = el('div', { class: 'attach-image-full' }, el('img', { src: 'data:' + a.mime + ';base64,' + a.dataBase64, alt: '附件大图：' + a.name }));
            row.appendChild(full);
          }
        });
        btns.appendChild(zoom);
      }
      if (a.dataBase64) {
        btns.appendChild(el('button', {
          class: 'icon-btn', type: 'button', title: '下载', 'aria-label': '下载附件', html: ICONS.download,
          onclick: function () {
            try { downloadBlob(b64ToBlob(a.dataBase64, a.mime), a.name); }
            catch (e) { toast('附件解码失败', 'err'); }
          }
        }));
      }
      row.appendChild(btns);
      grid.appendChild(row);
    });
    return grid;
  }

  function renderComposer(r, merged, pending) {
    var src = pending || merged || {};
    var composer = el('div', { class: 'composer' }, el('h4', { text: '处理与回复（生成 announcements.json 的 responses 条目）' }));

    var statusSel = el('select', { class: 'field-input', id: 'cp-status-' + r.id, 'aria-label': '处理状态' });
    COMPOSER_STATUS.forEach(function (s) {
      var o = el('option', { value: s, text: statusLabel(s) });
      if (s === (src.status || 'received')) o.selected = true;
      statusSel.appendChild(o);
    });
    var nameI = el('input', { class: 'field-input', type: 'text', maxlength: '40', placeholder: '受理人姓名', value: (src.assignee && src.assignee.name) || '' });
    var roleI = el('input', { class: 'field-input', type: 'text', maxlength: '40', placeholder: '角色（如 后端工程师）', value: (src.assignee && src.assignee.role) || '' });
    composer.appendChild(el('div', { class: 'form-row' },
      el('div', { class: 'field' }, el('label', { class: 'field-label', text: '状态' }), statusSel),
      el('div', { class: 'field' }, el('label', { class: 'field-label', text: '受理人' }), nameI),
      el('div', { class: 'field' }, el('label', { class: 'field-label', text: '角色' }), roleI)));

    var noteI = el('input', { class: 'field-input', type: 'text', maxlength: '300', placeholder: '处理节点备注（进入时间线，如：已定位为缓存键冲突）', value: (src.timeline && src.timeline.length ? src.timeline[src.timeline.length - 1].note : '') });
    composer.appendChild(el('div', { class: 'field' }, el('label', { class: 'field-label', text: '节点备注' }), noteI));

    var replyI = el('textarea', { class: 'field-input area', rows: '3', maxlength: '2000', placeholder: '回复 / 追问内容（可选；展示给用户，如：请补充浏览器控制台报错截图）' });
    if (src.replies && src.replies.length) replyI.value = src.replies[src.replies.length - 1].body;
    composer.appendChild(el('div', { class: 'field' }, el('label', { class: 'field-label', text: '回复 / 追问' }), replyI));

    function buildResponse() {
      var now = fmtShort(new Date());
      var name = clean(nameI.value, 40);
      var role = clean(roleI.value, 40);
      var note = clean(noteI.value, 300);
      var reply = clean(replyI.value, 2000);
      var resp = {
        reportId: r.id,
        status: statusSel.value,
        updatedAt: now,
        assignee: name ? { name: name, role: role } : null,
        timeline: note ? [{ status: statusSel.value, at: now, note: note }] : [],
        replies: reply ? [{ author: name || '开发者', role: role, body: reply, at: now }] : []
      };
      return resp;
    }
    var actions = el('div', { class: 'composer-actions' });
    actions.appendChild(el('button', {
      class: 'btn btn-primary btn-sm', type: 'button', html: ICONS.check + '<span>保存到待发布</span>',
      onclick: function () {
        dbPutResponse(buildResponse()).then(function () {
          toast('已保存待发布回复（' + r.id + '）', 'ok');
          renderAll();
        }).catch(function () { toast('保存失败（存储不可用）', 'err'); });
      }
    }));
    actions.appendChild(el('button', {
      class: 'btn btn-ghost btn-sm', type: 'button', html: ICONS.copy + '<span>复制本条 JSON</span>',
      onclick: function () { copyAndToast(JSON.stringify([buildResponse()], null, 2), '已复制 responses 条目（数组形式，可直接粘贴）'); }
    }));
    actions.appendChild(el('button', {
      class: 'btn btn-danger btn-sm', type: 'button', html: ICONS.trash + '<span>删除本条反馈</span>',
      onclick: function () {
        dbDeleteReport(r.id).then(function () {
          toast('已删除 ' + r.id, 'ok');
          renderAll();
        });
      }
    }));
    composer.appendChild(actions);
    if (merged) {
      composer.appendChild(el('p', { class: 'hint', text: '该反馈已有已发布回复；保存后请用同 reportId 条目替换 announcements.json 中的旧内容。' }));
    }
    return composer;
  }

  function renderPending(responses) {
    var panel = $('pending-panel');
    if (!panel) return;
    var list = $('pending-list');
    while (list.firstChild) list.removeChild(list.firstChild);
    $('pending-count').textContent = String(responses.length);
    panel.hidden = responses.length === 0;
    responses.forEach(function (resp) {
      var li = el('li', null,
        el('span', { class: 'mono', text: resp.reportId }),
        el('span', { class: 'badge tone-' + ((STATUS[resp.status] || STATUS.received).tone), text: statusLabel(resp.status) }),
        el('span', { class: 'grow muted', text: (resp.assignee && resp.assignee.name ? resp.assignee.name + ' · ' : '') + (resp.updatedAt || '') }),
        el('button', {
          class: 'icon-btn', type: 'button', title: '移除', 'aria-label': '移除待发布条目', html: ICONS.trash,
          onclick: function () {
            dbDeleteResponse(resp.reportId).then(function () { renderAll(); toast('已移除待发布条目', 'ok'); });
          }
        }));
      list.appendChild(li);
    });
  }

  /* ---------- 健康 / 时钟 ---------- */
  function checkHealth() {
    var pill = $('health-pill');
    var text = $('health-text');
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, 4000) : null;
    fetch(HEALTH_URL, { cache: 'no-store', signal: ctl ? ctl.signal : undefined })
      .then(function (r) { finish(r.ok ? 'ok' : 'down'); })
      .catch(function () { finish('down'); });
    function finish(state) {
      if (timer) clearTimeout(timer);
      if (pill) pill.dataset.state = state;
      if (text) text.textContent = state === 'ok' ? '后端正常' : '后端异常';
    }
  }
  function tick() {
    var c = $('clock');
    var d = new Date();
    if (c) c.textContent = fmtDateTime(d);
  }

  /* ---------- 事件 ---------- */
  function initEvents() {
    // 导入：拖放 / 选择
    var zone = $('import-zone');
    var input = $('import-input');
    zone.addEventListener('click', function () { input.click(); });
    zone.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); input.click(); }
    });
    ['dragenter', 'dragover'].forEach(function (t) {
      zone.addEventListener(t, function (ev) { ev.preventDefault(); zone.classList.add('dragover'); });
    });
    ['dragleave', 'drop'].forEach(function (t) {
      zone.addEventListener(t, function (ev) { ev.preventDefault(); zone.classList.remove('dragover'); });
    });
    zone.addEventListener('drop', function (ev) {
      var files = ev.dataTransfer && ev.dataTransfer.files;
      handleFiles(files);
    });
    input.addEventListener('change', function () {
      handleFiles(input.files);
      input.value = '';
    });
    function handleFiles(files) {
      if (!files || !files.length) return;
      var chain = Promise.resolve();
      Array.prototype.slice.call(files, 0, 10).forEach(function (f) {
        chain = chain.then(function () {
          return f.text().then(function (t) { return importJsonText(t, f.name); });
        });
      });
    }

    // 粘贴导入
    $('btn-toggle-paste').addEventListener('click', function () {
      var box = $('paste-box');
      box.hidden = !box.hidden;
      if (!box.hidden) $('paste-area').focus();
    });
    $('btn-cancel-text').addEventListener('click', function () {
      $('paste-box').hidden = true;
      $('paste-area').value = '';
    });
    $('btn-import-text').addEventListener('click', function () {
      importJsonText($('paste-area').value, '粘贴内容').then(function (ok) {
        if (ok) { $('paste-box').hidden = true; $('paste-area').value = ''; }
      });
    });

    // 搜索 / 过滤
    $('search').addEventListener('input', debounce(function () {
      currentFilter.q = $('search').value.trim().toLowerCase();
      renderAll();
    }, 200));
    $('status-filter').addEventListener('change', function () {
      currentFilter.status = $('status-filter').value;
      renderAll();
    });

    // 刷新已发布状态
    $('btn-refresh-published').addEventListener('click', function () {
      fetchAnnouncements(false).then(function () { toast('已刷新已发布状态', 'ok'); });
    });

    // 待发布
    $('btn-copy-all-responses').addEventListener('click', function () {
      dbAllResponses().then(function (responses) {
        if (!responses.length) { toast('暂无待发布回复', 'info'); return; }
        copyAndToast(JSON.stringify(responses, null, 2), '已复制全部 responses（粘贴到 announcements.json 的 responses 数组）');
      });
    });
    var clearRespBtn = $('btn-clear-responses');
    var clearTimer = null;
    clearRespBtn.addEventListener('click', function () {
      if (clearRespBtn.classList.contains('armed')) {
        dbClearResponses().then(function () { renderAll(); toast('已清空待发布回复', 'ok'); });
        clearRespBtn.classList.remove('armed');
        clearRespBtn.textContent = '清空待发布';
      } else {
        clearRespBtn.classList.add('armed');
        clearRespBtn.textContent = '确认清空？';
        clearTimeout(clearTimer);
        clearTimer = setTimeout(function () {
          clearRespBtn.classList.remove('armed');
          clearRespBtn.textContent = '清空待发布';
        }, 3000);
      }
    });

    // 轮询
    setInterval(function () { if (!document.hidden) fetchAnnouncements(true); }, ANN_POLL_MS);
    setInterval(function () { if (!document.hidden) checkHealth(); }, HEALTH_POLL_MS);
    setInterval(function () { if (!document.hidden && serverState === 'authed') loadServerList(); }, ANN_POLL_MS);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        fetchAnnouncements(true);
        checkHealth();
        initServerMode();
      }
    });

    // 服务端认证条：保存 Token 并重连
    $('btn-save-token').addEventListener('click', function () {
      var v = clean($('admin-token-input').value, 120);
      try {
        if (v) localStorage.setItem(K_ADMIN_KEY, v);
        else localStorage.removeItem(K_ADMIN_KEY);
      } catch (e) { /* 忽略 */ }
      initServerMode();
    });
    $('admin-token-input').addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') $('btn-save-token').click();
    });
    try {
      if (localStorage.getItem(K_ADMIN_KEY)) {
        $('admin-token-input').placeholder = '已保存（输入新值覆盖，清空则移除）';
      }
    } catch (e) { /* 忽略 */ }
  }

  /* ---------- 在线轨：服务端反馈（admin 认证，查看不落盘） ---------- */
  var API_BASE = '/feedback/api';
  var K_ADMIN_KEY = 'cgda-fb-console-key';
  var serverState = 'checking'; // checking | authed | unauthed | offline
  var serverAdmin = null;
  var serverOpenCards = {};
  var serverList = [];

  function fetchWithTimeout(url, opts, ms) {
    var ctl = ('AbortController' in window) ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, ms || 10000) : null;
    var merged = opts || {};
    if (ctl) merged.signal = ctl.signal;
    return fetch(url, merged).finally(function () { if (timer) clearTimeout(timer); });
  }
  function adminHeaders() {
    var key = '';
    try { key = localStorage.getItem(K_ADMIN_KEY) || ''; } catch (e) { /* 忽略 */ }
    return key ? { 'X-API-Key': key } : {};
  }
  function apiFetch(path, opts, ms) {
    var merged = opts || {};
    merged.headers = Object.assign({}, merged.headers || {}, adminHeaders());
    return fetchWithTimeout(API_BASE + path, merged, ms || 12000);
  }

  function setServerState(state, message) {
    serverState = state;
    var pill = $('server-state');
    var text = $('server-state-text');
    var bar = $('server-auth-bar');
    var hint = $('auth-hint');
    var actions = $('auth-actions');
    var map = {
      checking: ['checking', '检测中…'],
      authed: ['ok', serverAdmin ? ('已认证 · ' + serverAdmin.username) : '已认证'],
      unauthed: ['down', '未认证'],
      offline: ['down', '后端不可用']
    }[state] || ['checking', '检测中…'];
    if (pill) pill.dataset.state = map[0];
    if (text) text.textContent = map[1];
    if (bar) {
      if (state === 'authed' || state === 'checking') bar.hidden = true;
      else {
        bar.hidden = false;
        if (hint) {
          hint.textContent = state === 'offline'
            ? '后端暂不可用（维护期/宕机）：在线轨已暂停，本地导入与查看不受影响；恢复后自动重连。'
            : (message || '需要管理员身份：在主应用以 admin 登录后刷新本页（同域会话自动生效），或输入 Admin API Token / 服务密钥。');
        }
        if (actions) actions.hidden = state === 'offline';
      }
    }
  }

  function initServerMode() {
    setServerState('checking');
    apiFetch('/session', { cache: 'no-store' }, 6000)
      .then(function (r) {
        if (r.status === 401 || r.status === 403) {
          serverAdmin = null;
          setServerState('unauthed');
          return null;
        }
        if (!r.ok) throw new Error('http-' + r.status);
        return r.json().then(function (d) {
          serverAdmin = d || {};
          setServerState('authed');
          loadServerList();
        });
      })
      .catch(function () {
        setServerState('offline');
      });
  }

  function loadServerList() {
    if (serverState !== 'authed') return Promise.resolve();
    return apiFetch('/reports', { cache: 'no-store' }, 12000)
      .then(function (r) {
        if (!r.ok) throw new Error('http-' + r.status);
        return r.json();
      })
      .then(function (d) {
        serverList = (d && d.reports) || [];
        renderServerCards();
      })
      .catch(function () {
        setServerState('offline');
      });
  }

  function loadServerDetail(id) {
    return apiFetch('/reports/' + encodeURIComponent(id), { cache: 'no-store' }, 12000)
      .then(function (r) {
        if (!r.ok) throw new Error('http-' + r.status);
        return r.json();
      });
  }

  function renderServerCards() {
    var list = $('server-list');
    var count = $('server-count');
    if (count) count.textContent = String(serverList.length);
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);
    if (!serverList.length) {
      var empty = el('div', { class: 'empty-state' });
      empty.innerHTML = ICONS.inbox;
      empty.appendChild(el('p', { text: '服务器上暂无反馈。用户在反馈页点「上传到服务器」后会出现在这里。' }));
      list.appendChild(empty);
      return;
    }
    serverList.forEach(function (s) { list.appendChild(renderServerCard(s)); });
  }

  function renderServerCard(summary) {
    var id = summary.reportId;
    var sev = summary.severity || 'medium';
    var card = el('article', { class: 'server-card' });
    var idSpan = el('span', { class: 'report-id', text: id });
    var copyId = el('button', {
      class: 'icon-btn', type: 'button', title: '复制编号', 'aria-label': '复制反馈编号', html: ICONS.copy,
      onclick: function (ev) { ev.stopPropagation(); copyAndToast(id, '已复制反馈编号'); }
    });
    var chips = el('span', { class: 'card-id-row' }, idSpan, copyId);
    if (summary.hasResponse) chips.appendChild(el('span', { class: 'published-chip', text: '已有进展' }));

    var head = el('div', { class: 'console-card-head', role: 'button', tabindex: '0' },
      el('div', null, chips,
        el('h4', { class: 'card-title-line', text: summary.title || '（无标题）' }),
        el('div', { class: 'card-meta-line' },
          el('span', { text: (summary.submittedBy || '匿名') + (summary.createdAt ? ' · ' + summary.createdAt : '') }),
          summary.categoryLabel ? el('span', { text: summary.categoryLabel }) : null,
          el('span', { class: 'badge sev-' + sev, text: SEVERITY[sev] || sev }),
          el('span', { text: '附件 ' + (summary.attachmentCount || 0) + ' 个' }),
          summary.uploadedAt ? el('span', { text: '上传于 ' + summary.uploadedAt }) : null)),
      el('span', { class: 'badge tone-info' }, el('span', { class: 'dot' }), '服务端'));

    function toggle() {
      serverOpenCards[id] = !serverOpenCards[id];
      renderServerCards();
      if (serverOpenCards[id]) {
        loadServerDetail(id).then(function (detail) {
          serverOpenCards[id] = detail;
          renderServerCards();
        }).catch(function () {
          toast('加载详情失败（后端可能已离线）', 'err');
          serverOpenCards[id] = false;
          renderServerCards();
        });
      }
    }
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(); }
    });
    card.appendChild(head);

    var open = serverOpenCards[id];
    if (open) {
      var body = el('div', { class: 'console-card-body' });
      body.appendChild(renderServerBody(open === true ? summary : open, id));
      card.appendChild(body);
      card.classList.add('open');
    }
    return card;
  }

  function renderServerBody(detail, id) {
    var body = el('div', { class: 'detail-sections' });
    var r = detail.report || {};
    if (r.description) body.appendChild(section('问题描述', el('p', { class: 'detail-text', text: String(r.description).slice(0, 8000) })));
    if (r.steps) body.appendChild(section('复现步骤', el('p', { class: 'detail-text', text: String(r.steps).slice(0, 6000) })));
    if (r.expected || r.actual) {
      body.appendChild(section('期望 / 实际结果', el('p', { class: 'detail-text', text: '期望：' + (r.expected || '—') + '\n实际：' + (r.actual || '—') })));
    }
    var contact = r.contact || {};
    var contactRows = el('div', { class: 'env-grid' });
    [['提交人', contact.name], ['角色', contact.role], ['联系方式', contact.contact], ['设备标识', contact.deviceId]]
      .forEach(function (row) {
        if (row[1]) contactRows.appendChild(el('div', { class: 'kv' }, el('span', { class: 'kv-k', text: row[0] }), el('span', { class: 'kv-v', text: String(row[1]).slice(0, 200) })));
      });
    if (contactRows.childNodes.length) body.appendChild(section('提交人信息', contactRows));

    var env = r.env || {};
    if (Object.keys(env).length) {
      var envGrid = el('div', { class: 'env-grid' });
      Object.keys(env).slice(0, 30).forEach(function (k) {
        envGrid.appendChild(el('div', { class: 'kv' }, el('span', { class: 'kv-k', text: String(k).slice(0, 30) }), el('span', { class: 'kv-v', text: String(env[k]).slice(0, 200) })));
      });
      body.appendChild(section('环境信息', envGrid));
    }

    // 附件：经 API 下载/预览（cookie 或 X-API-Key 均可）
    var atts = detail.attachments || [];
    if (atts.length) {
      body.appendChild(section('附件（' + atts.length + '）', renderServerAttachments(id, atts)));
    }

    // 已发布进展
    var response = detail.response;
    if (response && response.replies && response.replies.length) {
      var replies = el('div', { class: 'replies' }, el('p', { class: 'replies-title', text: '已发布的回复与追问' }));
      response.replies.forEach(function (q) {
        replies.appendChild(el('div', { class: 'reply' },
          el('div', { class: 'reply-meta' },
            el('strong', { text: String(q.author || '开发者') + (q.role ? '（' + q.role + '）' : '') }),
            q.at ? el('span', { class: 'mono', text: String(q.at) }) : null),
          el('div', { class: 'reply-body', text: String(q.body || '').slice(0, 2000) })));
      });
      body.appendChild(replies);
    }
    body.appendChild(renderServerComposer(id, response));

    // 危险操作：删除服务端反馈（两步确认，不可恢复）
    var delBtn = el('button', {
      class: 'btn btn-danger btn-sm', type: 'button', html: ICONS.trash + '<span>删除该条服务端反馈</span>',
      onclick: function () {
        var label = delBtn.querySelector('span');
        if (!delBtn.classList.contains('armed')) {
          delBtn.classList.add('armed');
          if (label) label.textContent = ' 确认删除？（不可恢复）';
          setTimeout(function () {
            delBtn.classList.remove('armed');
            if (label) label.textContent = ' 删除该条服务端反馈';
          }, 4000);
          return;
        }
        delBtn.disabled = true;
        apiFetch('/reports/' + encodeURIComponent(id), { method: 'DELETE' }, 12000)
          .then(function (r) {
            if (!r.ok) throw new Error('http-' + r.status);
            delete serverOpenCards[id];
            toast('已删除服务端反馈 ' + id, 'ok');
            return loadServerList();
          })
          .catch(function () {
            delBtn.disabled = false;
            delBtn.classList.remove('armed');
            if (label) label.textContent = ' 删除该条服务端反馈';
            toast('删除失败（认证过期或后端不可用）', 'err');
          });
      }
    });
    body.appendChild(section('危险操作', delBtn));
    return body;
  }

  function renderServerAttachments(id, atts) {
    var grid = el('div', { class: 'attach-grid' });
    atts.forEach(function (a) {
      var name = String(a.name || '');
      // 相对路径（apiFetch 会自动拼接 API_BASE）
      var path = '/reports/' + encodeURIComponent(id) + '/attachments/' + encodeURIComponent(name);
      var row = el('div', { class: 'attach-row' });
      var btns = el('div', { class: 'attach-actions' });
      var isImage = /\.(png|jpe?g|gif|webp|bmp)$/i.test(name);
      if (isImage) {
        var imgWrap = null;
        btns.appendChild(el('button', {
          class: 'icon-btn', type: 'button', title: '预览图片', 'aria-label': '预览图片', html: ICONS.eye,
          onclick: function () {
            if (imgWrap && imgWrap.parentNode) { imgWrap.parentNode.removeChild(imgWrap); imgWrap = null; return; }
            apiFetch(path, {}, 20000).then(function (r) {
              if (!r.ok) throw new Error('http');
              return r.blob();
            }).then(function (blob) {
              var objUrl = URL.createObjectURL(blob);
              imgWrap = el('div', { class: 'attach-image-full' }, el('img', { src: objUrl, alt: '附件预览：' + name }));
              row.appendChild(imgWrap);
              setTimeout(function () { URL.revokeObjectURL(objUrl); }, 60000);
            }).catch(function () { toast('图片加载失败', 'err'); });
          }
        }));
      } else if (/\.(txt|log|json|csv|xml|ya?ml|toml|ini|cfg|conf|md|py|js|mjs|cjs|ts|vue|html?|css|scss|less|sql|r|sh|ps1|bat|env)$/i.test(name)) {
        var pre = null;
        btns.appendChild(el('button', {
          class: 'icon-btn', type: 'button', title: '预览文本', 'aria-label': '预览文本', html: ICONS.eye,
          onclick: function () {
            if (pre && pre.parentNode) { pre.parentNode.removeChild(pre); pre = null; return; }
            apiFetch(path, {}, 20000).then(function (r) {
              if (!r.ok) throw new Error('http');
              return r.text();
            }).then(function (txt) {
              pre = el('div', { class: 'attach-text-preview' }, el('pre', { text: txt.slice(0, 32 * 1024) + (txt.length > 32 * 1024 ? '\n…（已截断）' : '') }));
              row.appendChild(pre);
            }).catch(function () { toast('文本加载失败', 'err'); });
          }
        }));
      }
      btns.appendChild(el('button', {
        class: 'icon-btn', type: 'button', title: '下载', 'aria-label': '下载附件', html: ICONS.download,
        onclick: function () {
          apiFetch(path, {}, 30000).then(function (r) {
            if (!r.ok) throw new Error('http');
            return r.blob();
          }).then(function (blob) {
            downloadBlob(blob, name);
          }).catch(function () { toast('附件下载失败', 'err'); });
        }
      }));
      row.appendChild(el('span', { class: 'attach-thumb', html: isImage ? ICONS.image : ICONS.file }));
      row.appendChild(el('div', { class: 'attach-info' },
        el('div', { class: 'attach-name', text: name }),
        el('div', { class: 'attach-meta', text: fmtBytes(a.size || 0) })));
      row.appendChild(btns);
      grid.appendChild(row);
    });
    return grid;
  }

  function renderServerComposer(id, response) {
    var src = response || {};
    var composer = el('div', { class: 'composer' }, el('h4', { text: '发布处理进展（直接写入服务器，用户端可见）' }));
    var statusSel = el('select', { class: 'field-input', 'aria-label': '处理状态' });
    ['received', 'in_progress', 'needs_info', 'fixed', 'closed', 'rejected'].forEach(function (s) {
      var o = el('option', { value: s, text: statusLabel(s) });
      if (s === (src.status || 'received')) o.selected = true;
      statusSel.appendChild(o);
    });
    var nameI = el('input', { class: 'field-input', type: 'text', maxlength: '40', placeholder: '受理人姓名', value: (src.assignee && src.assignee.name) || '' });
    var roleI = el('input', { class: 'field-input', type: 'text', maxlength: '40', placeholder: '角色（如 后端工程师）', value: (src.assignee && src.assignee.role) || '' });
    composer.appendChild(el('div', { class: 'form-row' },
      el('div', { class: 'field' }, el('label', { class: 'field-label', text: '状态' }), statusSel),
      el('div', { class: 'field' }, el('label', { class: 'field-label', text: '受理人' }), nameI),
      el('div', { class: 'field' }, el('label', { class: 'field-label', text: '角色' }), roleI)));
    var noteI = el('input', { class: 'field-input', type: 'text', maxlength: '300', placeholder: '处理节点备注（进入时间线）', value: (src.timeline && src.timeline.length ? String(src.timeline[src.timeline.length - 1].note || '') : '') });
    composer.appendChild(el('div', { class: 'field' }, el('label', { class: 'field-label', text: '节点备注' }), noteI));
    var replyI = el('textarea', { class: 'field-input area', rows: '3', maxlength: '2000', placeholder: '回复 / 追问内容（可选；展示给用户）' });
    if (src.replies && src.replies.length) replyI.value = String(src.replies[src.replies.length - 1].body || '');
    composer.appendChild(el('div', { class: 'field' }, el('label', { class: 'field-label', text: '回复 / 追问' }), replyI));

    var nowStr = fmtShort(new Date());
    function buildBody() {
      return JSON.stringify({
        status: statusSel.value,
        updatedAt: nowStr,
        assignee: nameI.value.trim() ? { name: clean(nameI.value, 40), role: clean(roleI.value, 40) } : null,
        timeline: noteI.value.trim() ? [{ status: statusSel.value, at: nowStr, note: clean(noteI.value, 300) }] : [],
        replies: replyI.value.trim() ? [{ author: clean(nameI.value, 40) || '开发者', role: clean(roleI.value, 40), body: clean(replyI.value, 2000), at: nowStr }] : []
      });
    }
    var actions = el('div', { class: 'composer-actions' });
    actions.appendChild(el('button', {
      class: 'btn btn-primary btn-sm', type: 'button', html: ICONS.check + '<span>发布到服务器</span>',
      onclick: function (ev) {
        var btn = ev.currentTarget;
        btn.disabled = true;
        apiFetch('/reports/' + encodeURIComponent(id) + '/response', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: buildBody()
        }, 12000).then(function (r) {
          btn.disabled = false;
          if (!r.ok) throw new Error('http-' + r.status);
          toast('已发布进展（' + id + '），用户端 60 秒内可见', 'ok');
          loadServerList().then(function () {
            if (serverOpenCards[id] && serverOpenCards[id] !== true) {
              loadServerDetail(id).then(function (d) { serverOpenCards[id] = d; renderServerCards(); });
            }
          });
        }).catch(function () {
          btn.disabled = false;
          toast('发布失败（认证过期或后端不可用）', 'err');
        });
      }
    }));
    composer.appendChild(actions);
    return composer;
  }

  /* ---------- 启动 ---------- */
  function init() {
    initEvents();
    tick();
    setInterval(tick, 1000);
    checkHealth();
    initServerMode();
    fetchAnnouncements(true).then(renderAll);
    renderAll();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
