/**
 * 瓦片调度器：overlay PNG XYZ 瓦片的 请求队列 + 文件缓存（LRU）。
 *
 * 职责边界（方案 §4.3）：
 *  - 输入：WGS-84 视口 bounds + z（map-shell 每次 regionchange end / 图层/时间
 *    切换后调用 update()）
 *  - 内部：与当前 needed 集合 diff → 队列并发拉取（≤6）→ 写文件缓存
 *    （userData/tiles/）→ 每片就绪回调 onTileReady(tile, filePath)
 *  - 缓存命中（文件已存在）直接回调；LRU 上限 400 文件，超限淘汰最旧 80 个
 *  - 图层/时间切换：setActive() 重置 needed；旧时间瓦片文件留在缓存（可回切）
 */
var api = require('./api');
var merc = require('./geo/mercator');

var MAX_CONCURRENCY = 6;
var MAX_FILES = 400;
var EVICT_BATCH = 80;

var _fs = null;
var _dir = '';
var _active = { layerId: '', timeParam: '' };
var _needed = {}; // key -> tile {z,x,y,key}
var _queued = {}; // key -> true
var _fetching = 0;
var _fileIndex = []; // {key, path, ts}
var _callbacks = { onTileReady: null, onStatus: null };
var _stopped = false;

function _ensureFs() {
  if (_fs) {
    return;
  }
  _fs = wx.getFileSystemManager();
  _dir = wx.env.USER_DATA_PATH + '/tiles';
  try {
    _fs.mkdirSync(_dir, true);
  } catch (e) {
    /* 已存在 */
  }
}

function _key(t) {
  return _active.layerId + '_' + t.z + '_' + t.x + '_' + t.y + (_active.timeParam ? '_' + _active.timeParam : '');
}

function _path(key) {
  return _dir + '/' + key + '.png';
}

function _evictIfNeeded() {
  if (_fileIndex.length <= MAX_FILES) {
    return;
  }
  _fileIndex.sort(function (a, b) {
    return a.ts - b.ts;
  });
  var remove = _fileIndex.splice(0, EVICT_BATCH);
  remove.forEach(function (e) {
    try {
      _fs.unlinkSync(e.path);
    } catch (err) {
      /* ignore */
    }
  });
}

function _touchIndex(key, path) {
  for (var i = 0; i < _fileIndex.length; i++) {
    if (_fileIndex[i].key === key) {
      _fileIndex[i].ts = Date.now();
      return;
    }
  }
  _fileIndex.push({ key: key, path: path, ts: Date.now() });
  _evictIfNeeded();
}

function _status() {
  var total = Object.keys(_needed).length;
  var loaded = 0;
  Object.keys(_needed).forEach(function (k) {
    if (_fileExists(k)) {
      loaded++;
    }
  });
  if (_callbacks.onStatus) {
    _callbacks.onStatus({ loaded: loaded, total: total, fetching: _fetching });
  }
}

function _fileExists(key) {
  try {
    _fs.accessSync(_path(key));
    return true;
  } catch (e) {
    return false;
  }
}

/** 拉取单片：缓存命中即回调；否则 wx.request arraybuffer → 落盘 */
function _fetchTile(tile) {
  var key = tile.key;
  _ensureFs();

  if (_fileExists(key)) {
    _touchIndex(key, _path(key));
    if (_callbacks.onTileReady) {
      _callbacks.onTileReady(tile, _path(key));
    }
    _status();
    return;
  }

  if (_fetching >= MAX_CONCURRENCY) {
    return; // 由 pump 续
  }
  _fetching++;
  wx.request({
    url: api.tileUrl(_active.layerId, tile.z, tile.x, tile.y, _active.timeParam),
    method: 'GET',
    responseType: 'arraybuffer',
    timeout: 30000,
    header: { Cookie: wx.getStorageSync('cgda_session_cookie') || '' },
    success: function (res) {
      if (res.statusCode === 200 && res.data && res.data.byteLength > 0) {
        try {
          _fs.writeFileSync(_path(key), res.data, 'binary');
          _touchIndex(key, _path(key));
          if (_callbacks.onTileReady) {
            _callbacks.onTileReady(tile, _path(key));
          }
        } catch (e) {
          console.error('[tiles] write fail', key, e);
        }
      } else if (res.statusCode !== 200) {
        console.warn('[tiles] HTTP', res.statusCode, key);
      }
    },
    fail: function (err) {
      console.warn('[tiles] fetch fail', key, err.errMsg);
    },
    complete: function () {
      _fetching--;
      if (!_stopped) {
        _pump();
      }
      _status();
    }
  });
}

/** 队列泵：把未入队的 needed 瓦片按并发上限拉起 */
function _pump() {
  var keys = Object.keys(_needed);
  for (var i = 0; i < keys.length && _fetching < MAX_CONCURRENCY; i++) {
    var k = keys[i];
    if (_queued[k]) {
      continue;
    }
    var tile = _needed[k];
    if (_fileExists(k)) {
      // 已有文件（上一帧遗留），直接回调
      _touchIndex(k, _path(k));
      if (_callbacks.onTileReady) {
        _callbacks.onTileReady(tile, _path(k));
      }
      continue;
    }
    _queued[k] = true;
    _fetchTile(tile);
  }
  // 清理 queued 标记中已完成的（简化：每轮全清后由 needed 重建）
  Object.keys(_queued).forEach(function (k) {
    if (!_needed[k]) {
      delete _queued[k];
    }
  });
}

var tiles = {
  /**
   * 配置当前图层 + 时间。变更即重置 needed 集合（旧瓦片文件保留在缓存）。
   */
  setActive: function (layerId, timeParam) {
    _ensureFs();
    _active = { layerId: layerId, timeParam: timeParam || '' };
    _needed = {};
    _queued = {};
  },

  /**
   * 视口更新：bounds = WGS-84 {west,south,east,north}。
   * 返回 needed 瓦片数组（含 key），并开始拉取缺失片。
   */
  update: function (bounds, z) {
    _ensureFs();
    var list = merc.wgsTilesForBounds(bounds, z, 1);
    var next = {};
    list.forEach(function (t) {
      var k = _key(t);
      t.key = k;
      next[k] = t;
    });
    _needed = next;
    _pump();
    _status();
    return list;
  },

  onTileReady: function (fn) {
    _callbacks.onTileReady = fn;
  },

  onStatus: function (fn) {
    _callbacks.onStatus = fn;
  },

  /** 当前 needed 中已就绪的瓦片（含 filePath），供整帧重绘 */
  readyTiles: function () {
    _ensureFs();
    var out = [];
    Object.keys(_needed).forEach(function (k) {
      if (_fileExists(k)) {
        var t = _needed[k];
        out.push({ z: t.z, x: t.x, y: t.y, key: k, filePath: _path(k) });
      }
    });
    return out;
  },

  clear: function () {
    _needed = {};
    _queued = {};
  }
};

module.exports = tiles;
