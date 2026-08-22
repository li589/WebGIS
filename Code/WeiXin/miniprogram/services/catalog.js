/**
 * 图层目录服务：GET /layers + /layers/categories + /overlays →
 * 规范化为「分组 rail + 抽屉列表」模型，storage 缓存 10 分钟。
 *
 * M2 只暴露瓦片能力图层（PNG overlay）；weather（GeoJSON）图层 M3 接入。
 */
var api = require('./api');

var CACHE_KEY = 'cgda_catalog_cache';
var CACHE_TTL = 10 * 60 * 1000;

function _cacheValid(cached) {
  return cached && Date.now() - cached.ts < CACHE_TTL && cached.groups;
}

/** 归一化目录 */
function _normalize(items, categories, overlayIds) {
  var ovSet = {};
  overlayIds.forEach(function (id) {
    ovSet[id] = true;
  });

  var byId = {};
  items.forEach(function (i) {
    byId[i.layer_id] = i;
  });

  var catById = {};
  categories.forEach(function (c) {
    catById[c.id] = c;
  });

  // 只保留有 overlay 能力且在目录中的图层
  var layers = [];
  overlayIds.forEach(function (id) {
    var item = byId[id];
    if (!item || item.status === 'placeholder') {
      return;
    }
    layers.push({
      layerId: item.layer_id,
      displayName: item.display_name,
      description: item.description || '',
      category: item.category,
      supportsTime: !!item.supports_time,
      timeGranularity: item.time_granularity || null
    });
  });

  // 分组：只保留有图层的类别（weather 无 overlay 层 → M3 前不显示）
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
      count: itemsInCat.length
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

module.exports = { loadCatalog: loadCatalog };
