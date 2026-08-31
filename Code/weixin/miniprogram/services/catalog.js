/**
 * 图层目录服务：GET /layers + /layers/categories + /overlays →
 * 规范化为「分组 rail + 抽屉列表」模型，storage 缓存 10 分钟。
 *
 * 首屏不批量拉 /overlay-bounds（避免一进页就请求 dem-etopo 等全部图层）。
 * xyz 能力在用户选层时由 map-shell 拉 bounds 校验；目录侧仅按 /overlays 交集展示。
 */
var api = require('./api');

var CACHE_KEY = 'cgda_catalog_cache_v2';
var CACHE_TTL = 10 * 60 * 1000;
var BOUNDS_CACHE_KEY = 'cgda_bounds_cache';

function _cacheValid(cached) {
  return cached && Date.now() - cached.ts < CACHE_TTL && cached.groups;
}

function _readBoundsCache() {
  try {
    return wx.getStorageSync(BOUNDS_CACHE_KEY) || {};
  } catch (e) {
    return {};
  }
}

function _writeBoundsCache(cached) {
  try {
    wx.setStorageSync(BOUNDS_CACHE_KEY, cached);
  } catch (e) {
    /* ignore */
  }
}

/** 单层 bounds → 规范化 meta（供选层复用） */
function normalizeBoundsMeta(d) {
  var m = (d && d.meta) || {};
  return {
    palette: m.palette || 'viridis',
    vmin: m.vmin != null ? m.vmin : 0,
    vmax: m.vmax != null ? m.vmax : 1,
    unit: m.unit || '',
    opacity: typeof m.opacity === 'number' ? m.opacity : 0.85,
    minzoom: m.minzoom != null ? m.minzoom : 0,
    maxzoom: m.maxzoom != null ? m.maxzoom : 18,
    timeList: (m.time_list || m.timeList || []).map(String),
    tileUrlTemplate: m.tile_url_template || '',
    supportsXyzTiles: m.supports_xyz_tiles === true
  };
}

/** 按需拉取并缓存单层 meta（选层时调用） */
function fetchLayerMeta(layerId) {
  var cached = _readBoundsCache();
  if (cached[layerId]) {
    return Promise.resolve(cached[layerId]);
  }
  return api.getOverlayBounds(layerId).then(function (d) {
    var meta = normalizeBoundsMeta(d);
    cached[layerId] = meta;
    _writeBoundsCache(cached);
    return meta;
  });
}

/** 归一化目录（不做 bounds 批量 enrich） */
function _normalize(items, categories, overlayIds) {
  var byId = {};
  items.forEach(function (i) {
    byId[i.layer_id] = i;
  });

  var boundsCache = _readBoundsCache();
  var layers = [];
  overlayIds.forEach(function (id) {
    var item = byId[id];
    if (!item || item.status === 'placeholder') {
      return;
    }
    // 若本地已有 bounds 缓存且明确不支持 xyz，则目录里直接隐藏
    var cachedMeta = boundsCache[id];
    if (cachedMeta && cachedMeta.supportsXyzTiles === false) {
      return;
    }
    var layer = {
      layerId: item.layer_id,
      displayName: item.display_name,
      description: item.description || '',
      category: item.category,
      supportsTime: !!item.supports_time,
      timeGranularity: item.time_granularity || null
    };
    if (cachedMeta) {
      layer.meta = cachedMeta;
      layer.supportsTime = !!(cachedMeta.timeList && cachedMeta.timeList.length);
    }
    layers.push(layer);
  });

  var groups = {};
  var railCategories = [];
  categories.forEach(function (c) {
    var itemsInCat = layers.filter(function (l) {
      return l.category === c.id;
    });
    if (!itemsInCat.length) {
      return;
    }
    groups[c.id] = {
      id: c.id,
      name: c.name,
      icon: c.icon || c.id.slice(0, 1).toUpperCase(),
      accentColor: c.accent_color || '#185fa5',
      layers: itemsInCat
    };
    railCategories.push({
      id: c.id,
      name: c.name,
      icon: c.icon || c.id.slice(0, 1).toUpperCase(),
      accentColor: c.accent_color || '#185fa5',
      count: itemsInCat.length,
      layers: itemsInCat
    });
  });

  return {
    railCategories: railCategories,
    groups: groups,
    layerById: layers.reduce(function (acc, l) {
      acc[l.layerId] = l;
      return acc;
    }, {})
  };
}

function loadCatalog(force) {
  var cached = null;
  try {
    cached = wx.getStorageSync(CACHE_KEY) || null;
  } catch (e) {
    /* ignore */
  }
  if (!force && _cacheValid(cached)) {
    return Promise.resolve(cached.data);
  }
  api.init();
  return Promise.all([api.getCatalog(), api.getOverlayIds()]).then(function (rs) {
    var data = _normalize(rs[0].items, rs[0].categories, rs[1]);
    try {
      wx.setStorageSync(CACHE_KEY, { ts: Date.now(), data: data });
    } catch (e) {
      /* ignore */
    }
    return data;
  });
}

module.exports = {
  loadCatalog: loadCatalog,
  fetchLayerMeta: fetchLayerMeta,
  normalizeBoundsMeta: normalizeBoundsMeta
};
