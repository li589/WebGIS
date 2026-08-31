/**
 * 后端 API 客户端（CGDA FastAPI）。
 *
 * 部署形态（方案 §2.3）：
 *  - baseUrl 指向 CGDA 后端（无 /api 前缀）；开发期 http://127.0.0.1:8000 +
 *    project.config.json setting.urlCheck=false（不校验合法域名）。
 *  - 正式环境需 HTTPS 域名并加入小程序后台白名单，只改本文件 CONFIG。
 *
 * 鉴权：POST /auth/login（开发预填账号）→ 会话 cookie cgda_session；
 * 手动携带 Cookie 头（小程序不自动管理 cookie）；401 时自动重登一次。
 */

var CONFIG = {
  baseUrl: 'http://127.0.0.1:8000',
  username: 'admin',
  password: 'cgda-dev-admin'
};

var COOKIE_KEY = 'cgda_session_cookie';
var _cookie = '';

function init() {
  _cookie = wx.getStorageSync(COOKIE_KEY) || '';
}

function login() {
  return new Promise(function (resolve, reject) {
    wx.request({
      url: CONFIG.baseUrl + '/auth/login',
      method: 'POST',
      data: { username: CONFIG.username, password: CONFIG.password },
      header: { 'Content-Type': 'application/json' },
      timeout: 10000,
      success: function (res) {
        if (res.statusCode !== 200) {
          reject(new Error('login HTTP ' + res.statusCode));
          return;
        }
        var h = res.header || {};
        var sc = h['Set-Cookie'] || h['set-cookie'] || '';
        if (Array.isArray(sc)) {
          sc = sc.join('; ');
        }
        var m = /cgda_session=[^;]+/.exec(sc);
        if (!m) {
          reject(new Error('login 未返回 cgda_session cookie'));
          return;
        }
        _cookie = m[0];
        try {
          wx.setStorageSync(COOKIE_KEY, _cookie);
        } catch (e) {
          /* storage 满等不致命 */
        }
        resolve(_cookie);
      },
      fail: function (err) {
        reject(new Error(err.errMsg || 'login fail'));
      }
    });
  });
}

/** 通用请求：401 → 重登一次后重试 */
function request(path, opts) {
  opts = opts || {};
  return new Promise(function (resolve, reject) {
    var retried = false;

    var doReq = function () {
      wx.request({
        url: CONFIG.baseUrl + path,
        method: opts.method || 'GET',
        data: opts.data,
        timeout: opts.timeout || 20000,
        responseType: opts.binary ? 'arraybuffer' : 'text',
        header: Object.assign(
          { Cookie: _cookie || '' },
          opts.header || {}
        ),
        success: function (res) {
          if (res.statusCode === 401 && !retried) {
            retried = true;
            login().then(doReq).catch(reject);
            return;
          }
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(res.data);
          } else {
            reject(new Error('HTTP ' + res.statusCode + ' ' + path));
          }
        },
        fail: function (err) {
          reject(new Error(err.errMsg || 'request fail ' + path));
        }
      });
    };

    if (!_cookie) {
      login().then(doReq).catch(reject);
    } else {
      doReq();
    }
  });
}

/* ================= 业务端点 ================= */

/** 图层目录（items + categories） */
function getCatalog() {
  return Promise.all([request('/layers'), request('/layers/categories')]).then(
    function (rs) {
      return {
        items: rs[0].items || [],
        categories: rs[1].items || []
      };
    }
  );
}

/** 可用叠加图层 id 列表（有 GeoTIFF/瓦片能力） */
function getOverlayIds() {
  return request('/overlays').then(function (d) {
    return d.overlay_layer_ids || [];
  });
}

/** 图层边界 + 渲染元数据（palette/vmin/vmax/unit/time_list/tile 模板） */
function getOverlayBounds(layerId) {
  return request('/overlay-bounds/' + layerId);
}

/** 瓦片 URL（供 wx.request 拉二进制） */
function tileUrl(layerId, z, x, y, timeParam) {
  var u =
    CONFIG.baseUrl +
    '/overlay-tiles/' +
    layerId +
    '/' +
    z +
    '/' +
    x +
    '/' +
    y +
    '.png';
  if (timeParam) {
    u += '?time=' + timeParam;
  }
  return u;
}

module.exports = {
  CONFIG: CONFIG,
  init: init,
  login: login,
  request: request,
  getCatalog: getCatalog,
  getOverlayIds: getOverlayIds,
  getOverlayBounds: getOverlayBounds,
  tileUrl: tileUrl
};
