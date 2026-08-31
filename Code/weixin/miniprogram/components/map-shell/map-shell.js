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
// 进入页绝不自动选层 / 不拉 ETOPO 瓦片；仅用户从右侧工具栏点选后加载

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    center: { latitude: 39.9101, longitude: 116.4036 },
    scale: INITIAL_SCALE,
    satellite: false,
    markers: [],
    metersPerPixel: 0,
    debugHud: '',
    banner: '',
    /* 仅有活动图层时才挂载 canvas */
    showOverlayCanvas: false,
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
    timeline: { mode: 'static', ticks: [], current: 0 },
    tlHeight: 128
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
      // 必须等 MapContext 回传真实中心/缩放后再画瓦片，否则首帧投影错位会把
      // dem-etopo（terrain 黄米色）整屏糊成半透明黄罩。
      this._mapSynced = false;
      this._pendingLayerId = null;
      this.setData({
        center: { latitude: this._centerGcj.lat, longitude: this._centerGcj.lng }
      });

      tiles.onTileReady(function (tile, filePath) {
        if (!self._layer || !self.data.showOverlayCanvas) {
          return;
        }
        self._getImage(filePath, function () {
          self._drawOverlay('tile');
        });
      });
      tiles.onStatus(function (s) {
        self._tileStats = s;
        self._updateHud();
      });

      // 先起目录/地图对齐；canvas 仅在用户选层后挂载（见 _ensureOverlayCanvas）
      this._boot();
      // 稍后再同步相机（不等 canvas）
      setTimeout(function () {
        self._syncMapCamera(false);
      }, 300);
    },

    /* ================= M2: 目录 + 图层链路 ================= */

    _boot: function () {
      var self = this;
      api.init();
      catalogSvc
        .loadCatalog()
        .then(function (cat) {
          self._catalog = cat;
          // 右侧栏需要 categories[].layers；catalog 已挂在 railCategories 上
          var rails = (cat.railCategories || []).map(function (rc) {
            var g = cat.groups[rc.id];
            return Object.assign({}, rc, { layers: (g && g.layers) || rc.layers || [] });
          });
          self.setData({
            railCategories: rails,
            railActiveId: rails.length ? rails[0].id : ''
          });
          // 明确：不自动 selectLayer，不挂 canvas，不请求瓦片
        })
        .catch(function (err) {
          console.error('[map-shell] catalog fail', err);
          self.setData({ banner: '目录加载失败：' + (err.message || err) });
        });
    },

    /** 选层后按需创建 canvas，避免空/错 canvas 压在 UI 上 */
    _ensureOverlayCanvas: function (done) {
      var self = this;
      if (this._cv && this.data.showOverlayCanvas) {
        if (done) {
          done();
        }
        return;
      }
      this.setData({ showOverlayCanvas: true }, function () {
        var defer =
          typeof wx.nextTick === 'function'
            ? wx.nextTick
            : function (fn) {
                setTimeout(fn, 0);
              };
        defer(function () {
          self
            .createSelectorQuery()
            .select('#overlayCanvas')
            .fields({ node: true, size: true })
            .exec(function (res) {
              if (!res || !res[0] || !res[0].node) {
                console.error('[map-shell] canvas node 获取失败');
                self.setData({ banner: 'canvas 初始化失败', showOverlayCanvas: false });
                return;
              }
              var info = res[0];
              var win = wx.getWindowInfo ? wx.getWindowInfo() : { pixelRatio: 2 };
              var dpr = win.pixelRatio || 2;
              var canvas = info.node;
              var w = info.width || 0;
              var h = info.height || 0;
              if (w < 8 || h < 8) {
                console.warn('[map-shell] canvas size invalid', w, h);
                self.setData({ showOverlayCanvas: false });
                return;
              }
              canvas.width = w * dpr;
              canvas.height = h * dpr;
              var ctx = canvas.getContext('2d');
              ctx.setTransform(1, 0, 0, 1, 0, 0);
              ctx.scale(dpr, dpr);
              self._cv = { canvas: canvas, ctx: ctx, w: w, h: h, dpr: dpr };
              if (done) {
                done();
              }
            });
        });
      });
    },

    _teardownOverlayCanvas: function () {
      tiles.clear();
      this._imgCache = {};
      this._layer = null;
      this._cv = null;
      this.setData({
        showOverlayCanvas: false,
        activeLayer: { id: '', name: '' },
        colorbar: {
          visible: false,
          title: '',
          unit: '',
          paletteId: 'viridis',
          vmin: 0,
          vmax: 1
        },
        timeline: { mode: 'static', ticks: [], current: 0 },
        debugHud: ''
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

    /** right-tool-bar 选中图层事件接入：调 selectLayer 完成加载 */
    onToolBarSelect: function (e) {
      this.selectLayer(e.detail.layerId);
    },

    selectLayer: function (layerId) {
      var self = this;
      if (!layerId) {
        this._teardownOverlayCanvas();
        return;
      }
      // 演示占位 id 不请求后端
      if (String(layerId).indexOf('demo-') === 0) {
        this.setData({ banner: '演示图层，请连接后端后选择真实图层' });
        return;
      }

      this.setData({
        activeLayer: { id: layerId, name: layerId },
        banner: ''
      });
      this._imgCache = {};
      tiles.clear();

      var applyMeta = function (meta, displayName) {
        if (meta.supportsXyzTiles === false) {
          self.setData({
            banner: '该图层不支持 XYZ 瓦片，无法在小程序叠加显示',
            showOverlayCanvas: false
          });
          self._layer = null;
          self._cv = null;
          return;
        }
        var timeList = meta.timeList || [];
        var timeParam = timeList.length ? String(timeList[0]) : '';
        self._layer = {
          id: layerId,
          name: displayName || layerId,
          meta: meta,
          timeList: timeList.map(String),
          timeParam: timeParam,
          opacity: typeof meta.opacity === 'number' ? Math.min(meta.opacity, 0.75) : 0.7
        };
        if (self._catalog && self._catalog.layerById[layerId]) {
          self._catalog.layerById[layerId].meta = meta;
        }
        self.setData({
          activeLayer: { id: layerId, name: self._layer.name },
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
        if (!self._mapSynced) {
          self._pendingLayerId = layerId;
          self._syncMapCamera(true);
          return;
        }
        self._scheduleTiles();
      };

      var layerInfo = (this._catalog && this._catalog.layerById[layerId]) || null;
      var displayName = (layerInfo && layerInfo.displayName) || layerId;

      self._ensureOverlayCanvas(function () {
        if (self._cv && self._cv.ctx) {
          self._cv.ctx.clearRect(0, 0, self._cv.w, self._cv.h);
        }
        var metaP =
          layerInfo && layerInfo.meta && layerInfo.meta.supportsXyzTiles != null
            ? Promise.resolve(layerInfo.meta)
            : catalogSvc.fetchLayerMeta(layerId);
        metaP
          .then(function (meta) {
            applyMeta(meta, displayName);
          })
          .catch(function (err) {
            console.error('[map-shell] overlay-bounds fail', err);
            self.setData({ banner: '图层元数据加载失败：' + (err.message || err) });
          });
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

    /** 时间轴折叠/展开：同步更新 tlHeight，让比例尺/HUD/影像按钮跟随贴紧 */
    onTimelineCollapse: function (e) {
      var h = (e.detail && e.detail.height) || 128;
      this.setData({ tlHeight: h });
    },

    /** M2 后时间轴模式由图层驱动；此入口保留给自动化验证 */
    demoTimeline: function () {
      return this.data.timeline;
    },

    /* ================= 瓦片绘制 ================= */

    /** 视口变化 / 图层时间变化 → 重算 needed 瓦片并取片 */
    _scheduleTiles: function () {
      if (!this._layer || !this._cv || !this._mapSynced) {
        return;
      }
      if (!this._cv.w || !this._cv.h || this._cv.w < 8 || this._cv.h < 8) {
        return;
      }
      var meta = this._layer.meta || {};
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
      var rect = { x: p1.x, y: p1.y, w: p2.x - p1.x, h: p2.y - p1.y };
      // 期望边长 ≈ 256 * 2^(mapScale - tileZ)；超出过多即投影未对齐
      var expected = merc.TILE_SIZE * Math.pow(2, this._scale - t.z);
      var maxSide = Math.max(expected * 2.2, 64);
      if (
        !isFinite(rect.x) ||
        !isFinite(rect.y) ||
        !isFinite(rect.w) ||
        !isFinite(rect.h) ||
        rect.w <= 1 ||
        rect.h <= 1 ||
        rect.w > maxSide ||
        rect.h > maxSide ||
        rect.w > this._cv.w * 1.5 ||
        rect.h > this._cv.h * 1.5
      ) {
        return null;
      }
      return rect;
    },

    /** 从 MapContext 拉真实中心/缩放；首次成功后放开瓦片绘制 */
    _syncMapCamera: function (thenSchedule) {
      var self = this;
      var mc = wx.createMapContext('cgdaMap', this);
      mc.getCenterLocation({
        success: function (loc) {
          if (typeof loc.latitude !== 'number' || typeof loc.longitude !== 'number') {
            return;
          }
          mc.getScale({
            success: function (s) {
              if (typeof s.scale !== 'number' || !(s.scale > 0)) {
                return;
              }
              self._centerGcj = { lat: loc.latitude, lng: loc.longitude };
              self._scale = s.scale;
              var firstSync = !self._mapSynced;
              self._mapSynced = true;
              self._updateScaleBar();
              if (firstSync && self._pendingLayerId) {
                var id = self._pendingLayerId;
                self._pendingLayerId = null;
                self.selectLayer(id);
              } else if (thenSchedule || (firstSync && self._layer)) {
                self._scheduleTiles();
              } else {
                self._drawOverlay('camera-sync');
              }
            }
          });
        }
      });
    },

    onBannerTap: function () {
      this.setData({ banner: '' });
    },

    /* ================= 地图交互 ================= */

    onMapUpdated: function () {
      if (!this._mapSynced) {
        // 不对齐时不要 thenSchedule=true 误触发；无图层时 schedule 本就空跑
        this._syncMapCamera(!!this._layer || !!this._pendingLayerId);
      } else if (this._layer) {
        this._drawOverlay('map-updated');
      }
    },

    onRegionChange: function (e) {
      if (e.type !== 'end') {
        return; // 手势期间冻结上一帧（连续同步在 M3 优化）
      }
      this._syncMapCamera(true);
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

    /* ================= 左侧工具栏：地图操作（M3+ 新增） ================= */

    /** 放大地图：scale + 1（上限 20） */
    onZoomIn: function () {
      var self = this;
      var s = Math.min((this._scale || 12) + 1, 20);
      this._scale = s;
      this.setData({ scale: s }, function () {
        self._updateScaleBar();
        self._scheduleTiles();
      });
    },

    /** 缩小地图：scale - 1（下限 3） */
    onZoomOut: function () {
      var self = this;
      var s = Math.max((this._scale || 12) - 1, 3);
      this._scale = s;
      this.setData({ scale: s }, function () {
        self._updateScaleBar();
        self._scheduleTiles();
      });
    },

    /** 重置视角正北（本项目禁旋转倾斜，此方法为保险入口） */
    onResetNorth: function () {
      var mc = wx.createMapContext('cgdaMap', this);
      mc.setRotate && mc.setRotate({ rotate: 0 });
      mc.setSkew && mc.setSkew({ skew: 0 });
    },

    /** 定位到用户当前位置：
     *  首次调用 wx.getLocation 微信会自动弹授权窗；
     *  若用户曾拒绝过（errMsg 含 auth deny/denied），引导去设置页开启权限；
     *  其他失败（无 GPS 信号等）用 toast 简单提示。 */
    onLocate: function () {
      var self = this;
      wx.getLocation({
        type: 'gcj02',
        success: function (res) {
          var mc = wx.createMapContext('cgdaMap', self);
          mc.moveToLocation({
            latitude: res.latitude,
            longitude: res.longitude,
            success: function () {
              self._centerGcj = { lat: res.latitude, lng: res.longitude };
              mc.getScale({
                success: function (s) {
                  self._scale = s.scale;
                  self._updateScaleBar();
                  self._drawOverlay('locate');
                  self._scheduleTiles();
                }
              });
            },
            fail: function () {
              self.setData({ banner: '地图移动失败，请稍后再试' });
            }
          });
        },
        fail: function (err) {
          var msg = (err && err.errMsg) || '';
          if (msg.indexOf('auth deny') >= 0 || msg.indexOf('auth denied') >= 0) {
            // 用户曾经拒绝过定位授权 → 引导去设置页开启
            wx.showModal({
              title: '需要定位权限',
              content: '检测到您未授权定位，是否前往设置页开启定位权限？',
              confirmText: '去设置',
              cancelText: '取消',
              success: function (m) {
                if (m.confirm) {
                  wx.openSetting({
                    success: function (s) {
                      if (s.authSetting && s.authSetting['scope.userLocation']) {
                        // 用户在设置页开启了权限，自动重新定位
                        self.onLocate();
                      }
                    }
                  });
                }
              }
            });
          } else {
            wx.showToast({
              title: '定位失败，请检查设备 GPS',
              icon: 'none',
              duration: 2000
            });
          }
        }
      });
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
      if (!w || !h) {
        return;
      }
      ctx.clearRect(0, 0, w, h);

      // 地图相机未对齐前不画瓦片（只清屏），避免整屏黄罩
      if (!this._mapSynced) {
        this._updateHud();
        return;
      }

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
          if (!r || r.x > w || r.y > h || r.x + r.w < 0 || r.y + r.h < 0) {
            continue;
          }
          ctx.globalAlpha = opacity;
          try {
            ctx.drawImage(entry.img, r.x, r.y, r.w, r.h);
          } catch (err) {
            console.warn('[map-shell] drawImage fail', t.key, err);
          }
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
