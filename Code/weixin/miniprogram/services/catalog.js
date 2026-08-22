/**
 * 图层目录服务：GET /layers + /layers/categories + /overlays →
 * 规范化为「分组 rail + 抽屉列表」模型，storage 缓存 10 分钟。
 *
 * M2 过滤策略：仅保留 overlay-bounds.supports_xyz_tiles=true 的图层（后端
 * GDAL XYZ 切片能力；非 COG 缺金字塔的产品暂无法缩放瓦片渲染）。
 * 加载时并行拉所有 bounds 标注 xyz 能力，缓存复用于 selectLayer。
 */
var api = require('./api');

var CACHE_KEY = 'cgda_catalog_cache';
var CACHE_TTL = 10 * 60 * 1000;

function _cacheValid(cached) {
  return cached && Date.now() - cached.ts < CACHE_TTL && cached.groups;
}

/** 标注每个图层的 xyz/时间能力 */
function _enrichLayers(layerList, overlayIds) {
  var ids = layerList.map(function (l) {
    return l.layerId;
  });
  // 已有 bounds 缓存复用（避免重复拉）
  var cached = {};
  try {
    var raw = wx.getStorageSync('cgda_bounds_cache') || {};
    cached = raw || {};
  } catch (e) {
    /* ignore */
  }
  return Promise.all(
    ids.map(function (id) {
      if (cached[id]) {
        return Promise.resolve(cached[id]);
      }
      return api.getOverlayBounds(id).then(function (d) {
        var m = (d && d.meta) || {};
        var meta = {
          palette: m.palette || 'viridis',
          vmin: m.vmin != null ? m.vmin : 0,
          vmax: m.vmax != null ? m.vmax : 1,
          unit: m.unit || '',
          opacity: typeof m.opacity === 'number' ? m.opacity : 0.85,
          minzoom: m.minzoom != null ? m.minzoom : 0,
          maxzoom: m.maxzoom != null ? m.maxzoom : 18,
          timeList: (m.time_list || []).map(String),
          tileUrlTemplate: m.tile_url_template || '',
          supportsXyzTiles: m.supports_xyz_tiles === true
        };
        cached[id] = meta;
        return meta;
      }).catch(function () {
        return {
          supportsXyzTiles: false,
          palette: 'viridis',
          vmin: 0,
          vmax: 1,
          unit: '',
          opacity: 0.85,
          minzoom: 0,
          maxzoom: 18,
          timeList: []
        };
      });
    })
  ).then(function (metas) {
    try {
      wx.setStorageSync('cgda_bounds_cache', cached);
    } catch (e) {
      /* ignore */
    }
    layerList.forEach(function (l, i) {
      l.meta = metas[i];
    });
    return layerList;
  });
}

/** 归一化目录 */
function _normalize(items, categories, overlayIds) {
  var byId = {};
  items.forEach(function (i) {
    byId[i.layer_id] = i;
  });

  // 仅保留有 overlay 能力、目录可见的图层（xyz 支持后续 enrich 时再二次过滤）
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
    // enrich + 二次过滤 xyz
    var allLayers = [];
    Object.keys(data.layerById).forEach(function (k) {
      allLayers.push(data.layerById[k]);
    });
    return _enrichLayers(allLayers, rs[1]).then(function () {
      // 移除不支持 xyz 的图层
      Object.keys(data.groups).forEach(function (catId) {
        data.groups[catId].layers = data.groups[catId].layers.filter(function (l) {
          return l.meta && l.meta.supportsXyzTiles;
        });
      });
      // 重算分组/rail（隐藏空的）
      data.railCategories = data.railCategories
        .map(function (rc) {
          var g = data.groups[rc.id];
          return Object.assign({}, rc, { count: g ? g.layers.length : 0 });
        })
        .filter(function (rc) {
          return rc.count > 0;
        });
      Object.keys(data.groups).forEach(function (catId) {
        var g = data.groups[catId];
        if (!g.layers.length) {
          delete data.groups[catId];
        }
      });
      // layerById 同步
      data.layerById = {};
      data.railCategories.forEach(function (rc) {
        data.groups[rc.id].layers.forEach(function (l) {
          data.layerById[l.layerId] = l;
        });
      });
      try {
        wx.setStorageSync(CACHE_KEY, { ts: Date.now(), data: data });
      } catch (e) {
        /* ignore */
      }
      return data;
    });
  });
}

module.exports = { loadCatalog: loadCatalog };