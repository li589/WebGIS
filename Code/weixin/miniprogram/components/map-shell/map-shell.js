/**
 * map-shell —— 全屏地图壳（M0 对齐引擎 + M1 控件 + M2 图层链路）。
 *
 * 核心链路（方案 §4）：
 *  api.login → catalog(/layers + /categories + /overlays) → rail/drawer
 *  → selectLayer → /overlay-bounds（palette/vmin/vmax/time_list）
 *  → colorbar 自动 + timeline 时间域适配 + tiles 调度器
 *  → regionchange(end) 重算视口 WGS-84 瓦片集合 → canvas 绘制
 *
 * 坐标系约定：map 组件 = GCJ-02；后端 = WGS-84；屏幕投影统一 mercator.project(GCJ-02)。
 */
var gcj = require('../../services/geo/gcj02');
var merc = require('../../services/geo/mercator');
var api = require('../../services/api');
var catalogSvc = require('../../services/catalog');
var tiles = require('../../services/tiles');
var palettes = require('../../services/palettes');

var INITIAL_SCALE = 12;
var DEFAULT_LAYER_ID = 'dem-etopo'; // 后端 XYZ 能力薄：默认全局静态地形（其他 xyz 支持层：co2/cmfd-precip/clcd）

Component({
  data: {
    center: { latitude: 39.9101, longitude: 116.4036 },
    scale: INITIAL_SCALE,
    satellite: false,
    markers: [],
    metersPerPixel: 0,
    debugHud: '',
    banner: '',
    /* M2 图层链路 */
    railCategories: [],
    railActiveId: '',
    drawerVisible: false,
    drawerGroup: { name: '', layers: [] },
    drawerLoading: false,
    activeLayer: { id: '', name: '' },
    colorbar: {
      visible: false,
      title: '',
      unit: '',
      paletteId: 'viridis',
      vmin: 0,
      vmax: 1
    },
    timeline: { mode: 'static', ticks: [], current: 0 }
  },

  lifetimes: {
    ready: function () {
      this._init();
    }
  },

  methods: {
    _init: function () {
      var self = this;
      this._scale = INITIAL_SCALE;
      this._centerGcj = { lat: 39.9101, lng: 116.4036 }; // 北京（GCJ-02）
      this._tapDots = [];
      this._imgCache = {}; // filePath -> {img, ready}
      this._layer = null; // {id, name, meta, timeList, timeParam, ticks}
      this._tileStats = { loaded: 0, total: 0, fetching: 0 };
      this.setData({
        center: { latitude: this._centerGcj.lat, longitude: this._centerGcj.lng }
      });

      tiles.onTileReady(function (tile, filePath) {
        self._getImage(filePath, function () {
          self._drawOverlay('tile');
        });
      });
      tiles.onStatus(function (s) {
        self._tileStats = s;
        self._updateHud();
      });

      this.createSelectorQuery()
        .select('#overlayCanvas')
        .fields({ node: true, size: true })
        .exec(function (res) {
          if (!res || !res[0] || !res[0].node) {
            console.error('[map-shell] canvas node 获取失败');
            self.setData({ banner: 'canvas 初始化失败' });
            return;
          }
          var info = res[0];
          var win = wx.getWindowInfo ? wx.getWindowInfo() : { pixelRatio: 2 };
          var dpr = win.pixelRatio || 2;
          var canvas = info.node;
          canvas.width = info.width * dpr;
          canvas.height = info.height * dpr;
          var ctx = canvas.getContext('2d');
          ctx.scale(dpr, dpr);
          self._cv = { canvas: canvas, ctx: ctx, w: info.width, h: info.height, dpr: dpr };
          self._updateScaleBar();
          self._boot();
        });
    },

    /* ================= M2: 目录 + 图层链路 ================= */

    _boot: function () {
      var self = this;
      api.init();
      catalogSvc
        .loadCatalog()
        .then(function (cat) {
          self._catalog = cat;
          self.setData({
            railCategories: cat.railCategories,
            railActiveId: cat.railCategories.length ? cat.railCategories[0].id : ''
          });
          // 默认图层：优先 GPCP 月降水（全局 + 时间序列，可演示 timeline）
          var first = cat.railCategories.length ? cat.railCategories[0].id : '';
          var prefer =
            cat.layerById[DEFAULT_LAYER_ID] ||
            (cat.groups[first] && cat.groups[first].layers[0]);
          if (prefer) {
            self.selectLayer(prefer.layerId);
          }
        })
        .catch(function (err) {
          console.error('[map-shell] catalog fail', err);
          self.setData({ banner: '目录加载失败：' + (err.message || err) });
        });
    },

    onRailSelect: function (e) {
      var id = e.detail.id;
      var group = (this._catalog && this._catalog.groups[id]) || { name: e.detail.name, layers: [] };
      this.setData({
        railActiveId: id,
        drawerGroup: group,
        drawerVisible: true,
        drawerLoading: !group.layers.length
      });
    },

    onDrawerClose: function () {
      this.setData({ drawerVisible: false });
    },

    onDrawerSelect: function (e) {
      var layerId = e.detail.layerId;
      this.setData({ drawerVisible: false });
      this.selectLayer(layerId);
    },

    selectLayer: function (layerId) {
      var self = this;
      var layerInfo = (this._catalog && this._catalog.layerById[layerId]) || null;
      var boundsP = layerInfo && layerInfo.meta
        ? Promise.resolve({
            meta: layerInfo.meta,
            bounds: [layerInfo.meta.minzoom != null ? -180 : -180]
          })
        : api.getOverlayBounds(layerId);

      this.setData({
        activeLayer: { id: layerId, name: (layerInfo && layerInfo.displayName) || layerId },
        banner: ''
      });

      boundsP.then(function (d) {
        var meta = (d && d.meta) || {};
        var timeList = meta.timeList || meta.time_list || [];
        var timeParam = timeList.length ? String(timeList[0]) : '';

        self._layer = {
          id: layerId,
          name: (layerInfo && layerInfo.displayName) || layerId,
          meta: meta,
          timeList: timeList.map(String),
          timeParam: timeParam,
          opacity: typeof meta.opacity === 'number' ? meta.opacity : 0.85
        };

        self.setData({
          colorbar: {
            visible: true,
            title: self._layer.name,
            unit: meta.unit || '',
            paletteId: meta.palette || 'viridis',
            vmin: meta.vmin != null ? meta.vmin : 0,
            vmax: meta.vmax != null ? meta.vmax : 1
          }
        });

        self._buildTimelineFromTimeList(self._layer.timeList);
        tiles.setActive(layerId, timeParam);
        self._scheduleTiles();
      }).catch(function (err) {
        console.error('[map-shell] overlay-bounds fail', err);
        self.setData({ banner: '图层元数据加载失败：' + (err.message || err) });
      });
    },

    /** 时间轴数据域：time_list 空 → static；YYYYMM → month；YYYYMMDD → day */
    _buildTimelineFromTimeList: function (timeList) {
      var ticks = [];
      var mode = 'static';

      if (timeList && timeList.length > 1) {
        var s = String(timeList[0]);
        if (s.length === 6) {
          mode = 'month';
          ticks = this._ticksMonthly(timeList);
        } else if (s.length === 8) {
          mode = 'day';
          ticks = this._ticksDaily(timeList);
        } else {
          mode = 'day';
          ticks = timeList.map(function (t, i) {
            return {
              pos: (i * 100) / (timeList.length - 1),
              main: String(t),
              sub: '第' + (i + 1) + '/' + timeList.length + '期',
              major: i === 0,
              majorLabel: i === 0 ? '起点' : '',
              align: i === 0 ? 'left' : i === timeList.length - 1 ? 'right' : 'center'
            };
          });
        }
      }

      if (!ticks.length) {
        ticks = [{ pos: 0, main: '静态数据', sub: '该图层无时间维度', major: false, majorLabel: '', align: 'left' }];
      }
      this.setData({ timeline: { mode: mode, ticks: ticks, current: 0 } });
    },

    _ticksMonthly: function (list) {
      var n = list.length;
      return list.map(function (t, i) {
        var y = t.slice(0, 4);
        var m = parseInt(t.slice(4, 6), 10);
        return {
          pos: (i * 100) / (n - 1),
          main: y + '年' + m + '月',
          sub: '月度 · ' + (i + 1) + '/' + n,
          major: i === 0 || m === 1,
          majorLabel: i === 0 ? '起点' : m === 1 ? y + '年' : '',
          align: i === 0 ? 'left' : i === n - 1 ? 'right' : 'center'
        };
      });
    },

    _ticksDaily: function (list) {
      var n = list.length;
      return list.map(function (t, i) {
        var y = t.slice(0, 4);
        var m = parseInt(t.slice(4, 6), 10);
        var d = parseInt(t.slice(6, 8), 10);
        return {
          pos: (i * 100) / (n - 1),
          main: m + '月' + d + '日',
          sub: y + '年 · ' + (i + 1) + '/' + n,
          major: i === 0 || d === 1,
          majorLabel: i === 0 ? '起点' : d === 1 ? m + '月' : '',
          align: i === 0 ? 'left' : i === n - 1 ? 'right' : 'center'
        };
      });
    },

    /** 时间轴拖动 / 播放：切换 timeParam → 重新调度瓦片 */
    onTimelineChange: function (e) {
      var idx = e.detail.index;
      this.setData({ 'timeline.current': idx });
      if (!this._layer || !this._layer.timeList.length) {
        return;
      }
      var timeParam = this._layer.timeList[idx] || '';
      if (timeParam === this._layer.timeParam) {
        return;
      }
      this._layer.timeParam = timeParam;
      tiles.setActive(this._layer.id, timeParam);
      this._scheduleTiles();
    },

    onTimelineToggle: function (e) {
      console.log('[map-shell] timeline playing =', e.detail.playing);
    },

    /** M2 后时间轴模式由图层驱动；此入口保留给自动化验证 */
    demoTimeline: function () {
      return this.data.timeline;
    },

    /* ================= 瓦片绘制 ================= */

    /** 视口变化 / 图层时间变化 → 重算 needed 瓦片并取片 */
    _scheduleTiles: function () {
      if (!this._layer || !this._cv) {
        return;
      }
      var meta = this._layer.meta;
      var minZ = meta.minzoom != null ? meta.minzoom : 0;
      var maxZ = meta.maxzoom != null ? meta.maxzoom : 18;
      var z = Math.round(this._scale);
      z = Math.max(minZ, Math.min(maxZ, z, 19));

      var bGcj = merc.viewportBounds(this._centerGcj, this._scale, this._cv.w, this._cv.h);
      var nw = gcj.gcj02ToWgs84(bGcj.west, bGcj.north);
      var se = gcj.gcj02ToWgs84(bGcj.east, bGcj.south);
      var wgsBounds = { west: nw.lng, north: nw.lat, east: se.lng, south: se.lat };

      tiles.update(wgsBounds, z);
      this._drawOverlay('schedule');
    },

    /** filePath → canvas Image（带缓存；onload 后回调重绘） */
    _getImage: function (filePath, onload) {
      var self = this;
      var hit = this._imgCache[filePath];
      if (hit) {
        if (hit.ready && onload) {
          onload();
        }
        return hit.img;
      }
      var img = this._cv.canvas.createImage();
      var entry = { img: img, ready: false };
      this._imgCache[filePath] = entry;
      img.onload = function () {
        entry.ready = true;
        if (onload) {
          onload();
        }
      };
      img.onerror = function () {
        console.warn('[map-shell] image load fail', filePath);
      };
      img.src = filePath;
      return img;
    },

    /**
     * 瓦片（整数 z 级 WGS-84 网格）→ 屏幕矩形：
     * 角点 WGS-84 → GCJ-02 → P()（与底图严格同链路，含火星偏移）。
     */
    _tileRect: function (t) {
      var world = merc.worldSize(t.z);
      var nw = merc.unproject(t.x * merc.TILE_SIZE, t.y * merc.TILE_SIZE, world);
      var se = merc.unproject((t.x + 1) * merc.TILE_SIZE, (t.y + 1) * merc.TILE_SIZE, world);
      var nwG = gcj.wgs84ToGcj02(nw.lng, nw.lat);
      var seG = gcj.wgs84ToGcj02(se.lng, se.lat);
      var p1 = this._project(nwG.lat, nwG.lng);
      var p2 = this._project(seG.lat, seG.lng);
      return { x: p1.x, y: p1.y, w: p2.x - p1.x, h: p2.y - p1.y };
    },

    /* ================= 地图交互 ================= */

    onMapUpdated: function () {
      this._drawOverlay('map-updated');
    },

    onRegionChange: function (e) {
      if (e.type !== 'end') {
        return; // 手势期间冻结上一帧（连续同步在 M3 优化）
      }
      var self = this;
      var mc = wx.createMapContext('cgdaMap', this);
      mc.getCenterLocation({
        success: function (loc) {
          mc.getScale({
            success: function (s) {
              self._centerGcj = { lat: loc.latitude, lng: loc.longitude };
              self._scale = s.scale;
              self._updateScaleBar();
              self._drawOverlay('regionchange');
              self._scheduleTiles();
            }
          });
        }
      });
    },

    onMapTap: function (e) {
      var d = e.detail || {};
      if (typeof d.latitude !== 'number' || typeof d.longitude !== 'number') {
        return;
      }
      var wgs = gcj.gcj02ToWgs84(d.longitude, d.latitude);
      this._tapDots.push({ lat: d.latitude, lng: d.longitude });
      if (this._tapDots.length > 5) {
        this._tapDots.shift();
      }
      console.log('[map-shell] tap gcj=', d.longitude.toFixed(6), d.latitude.toFixed(6),
        '→ wgs=', wgs.lng.toFixed(6), wgs.lat.toFixed(6));
      this._drawOverlay('tap');
    },

    toggleSatellite: function () {
      this.setData({ satellite: !this.data.satellite });
    },

    /* ================= M0 自检（对齐验证，保留） ================= */

    _selfTest: function () {
      var self = this;
      if (!this._cv) {
        return { started: false, reason: 'canvas not ready' };
      }
      wx.createMapContext('cgdaMap', this).getRegion({
        success: function (r) {
          var pSW = self._project(r.southwest.latitude, r.southwest.longitude);
          var pNE = self._project(r.northeast.latitude, r.northeast.longitude);
          var w = self._cv.w;
          var h = self._cv.h;
          var result = {
            sw: { x: Math.round(pSW.x * 10) / 10, y: Math.round(pSW.y * 10) / 10 },
            ne: { x: Math.round(pNE.x * 10) / 10, y: Math.round(pNE.y * 10) / 10 },
            canvas: { w: w, h: h },
            errSWpx: Math.round(Math.max(Math.abs(pSW.x - 0), Math.abs(pSW.y - h)) * 10) / 10,
            errNEpx: Math.round(Math.max(Math.abs(pNE.x - w), Math.abs(pNE.y - 0)) * 10) / 10,
            scale: self._scale
          };
          self._selfTestResult = result;
          console.log('[M0 self-test]', JSON.stringify(result));
        },
        fail: function (e) {
          self._selfTestResult = { fail: true, err: e };
        }
      });
      return { started: true };
    },

    /* ================= 绘制与基础 ================= */

    _updateScaleBar: function () {
      var mpp = merc.metersPerPixel(this._centerGcj.lat, this._scale);
      this.setData({ metersPerPixel: mpp });
    },

    _project: function (latGcj, lngGcj) {
      var world = merc.worldSize(this._scale);
      var p = merc.project(lngGcj, latGcj, world);
      var c = merc.project(this._centerGcj.lng, this._centerGcj.lat, world);
      return { x: p.x - c.x + this._cv.w / 2, y: p.y - c.y + this._cv.h / 2 };
    },

    _updateHud: function () {
      var mpp = merc.metersPerPixel(this._centerGcj.lat, this._scale);
      var s = this._tileStats || {};
      var lines = [];
      if (this._layer) {
        lines.push(this._layer.name + (this._layer.timeParam ? ' @ ' + this._layer.timeParam : ''));
      }
      lines.push(
        'z ' + this._scale.toFixed(1) + ' | ' + mpp.toFixed(0) + ' m/px | 瓦片 ' +
        (s.loaded || 0) + '/' + (s.total || 0) +
        (s.fetching ? ' +' + s.fetching : '')
      );
      this.setData({ debugHud: lines.join('\n') });
    },

    _drawOverlay: function (reason) {
      if (!this._cv || !this._centerGcj) {
        return;
      }
      var ctx = this._cv.ctx;
      var w = this._cv.w;
      var h = this._cv.h;
      ctx.clearRect(0, 0, w, h);

      // ---- 1) 数据瓦片（overlay PNG） ----
      if (this._layer) {
        var ready = tiles.readyTiles();
        var opacity = this._layer.opacity;
        for (var i = 0; i < ready.length; i++) {
          var t = ready[i];
          var entry = this._imgCache[t.filePath];
          if (!entry || !entry.ready) {
            continue;
          }
          var r = this._tileRect(t);
          if (r.x > w || r.y > h || r.x + r.w < 0 || r.y + r.h < 0) {
            continue;
          }
          ctx.globalAlpha = opacity;
          ctx.drawImage(entry.img, r.x, r.y, r.w, r.h);
        }
        ctx.globalAlpha = 1;
      }

      // ---- 2) 点击十字（M4 点取值用） ----
      for (var d = 0; d < this._tapDots.length; d++) {
        var td = this._project(this._tapDots[d].lat, this._tapDots[d].lng);
        ctx.beginPath();
        ctx.moveTo(td.x - 7, td.y);
        ctx.lineTo(td.x + 7, td.y);
        ctx.moveTo(td.x, td.y - 7);
        ctx.lineTo(td.x, td.y + 7);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = '#378add';
        ctx.stroke();
      }

      this._updateHud();
    }
  }
});
