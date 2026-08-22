/**
 * map-shell —— 全屏地图壳（M0 spike 核心 + M1 控件宿主）。
 *
 * M0 验证目标：
 *  1. canvas(type=2d) 同层渲染覆盖 map，且 pointer-events:none 透传手势；
 *  2. regionchange(end) → getCenterLocation/getScale → mercator 重绘，
 *     WGS84 测试网格经 GCJ02 纠偏后与底图要素错位 < 5px；
 *  3. map marker（GCJ02）与 canvas 地标圆点（WGS84→GCJ02→屏幕）重合；
 *  4. enable-satellite 影像切换正常。
 *
 * 坐标系约定：map 组件一切坐标 = GCJ-02；后端 = WGS-84。
 * 屏幕投影统一走 mercator.project(GCJ02)。
 */
var gcj = require('../../services/geo/gcj02');
var merc = require('../../services/geo/mercator');

// M0 验证地标：天安门（WGS-84）
var LANDMARK_WGS = { lng: 116.3974, lat: 39.9087 };
var INITIAL_SCALE = 12;

var WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
var TIMELINE_MODES = ['hour', 'day', 'month', 'static'];

function pad2(n) {
  return n < 10 ? '0' + n : '' + n;
}

Component({
  data: {
    center: { latitude: 39.9087, longitude: 116.3974 }, // 初始化时会被 GCJ02 值覆盖
    scale: INITIAL_SCALE,
    satellite: false,
    markers: [],
    metersPerPixel: 0,
    debugHud: '',
    timeline: { mode: 'hour', ticks: [], current: 0 }
  },

  lifetimes: {
    ready: function () {
      this._init();
    }
  },

  methods: {
    _init: function () {
      this._scale = INITIAL_SCALE;
      this._centerGcj = gcj.wgs84ToGcj02(LANDMARK_WGS.lng, LANDMARK_WGS.lat);
      this._tapDots = [];
      this.setData({
        center: { latitude: this._centerGcj.lat, longitude: this._centerGcj.lng }
      });
      this._buildTimeline('hour');

      var self = this;
      this.createSelectorQuery()
        .select('#overlayCanvas')
        .fields({ node: true, size: true })
        .exec(function (res) {
          if (!res || !res[0] || !res[0].node) {
            console.error('[map-shell] canvas node 获取失败');
            self.setData({ debugHud: 'canvas node 获取失败' });
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

          // M0 重合验证：map marker（GCJ02 直给）vs canvas 圆点（WGS→GCJ→屏幕）
          self.setData({
            markers: [
              {
                id: 1,
                latitude: self._centerGcj.lat,
                longitude: self._centerGcj.lng,
                width: 24,
                height: 24
              }
            ]
          });
          self._updateScaleBar();
          self._drawOverlay('init');
        });
    },

    onMapUpdated: function () {
      // 底图瓦片就绪后补一帧，避免底图晚于叠加层出现
      this._drawOverlay('map-updated');
    },

    onRegionChange: function (e) {
      if (e.type !== 'end') {
        return; // 手势期间冻结上一帧（M3 再做连续同步）
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
            }
          });
        }
      });
    },

    onMapTap: function (e) {
      var d = e.detail || {};
      if (typeof d.latitude !== 'number' || typeof d.longitude !== 'number') {
        console.warn('[map-shell] map tap 未返回经纬度', d);
        return;
      }
      // tap 返回 GCJ-02；转 WGS-84 供后端 API 使用（M4 点取值链路验证）
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

    /* ================= 时间轴（M3-UI） ================= */

    /**
     * 生成四种时间域的 ticks（M2 接图层后由 layer descriptor 的时间能力驱动，
     * 当前为演示域：hour=未来48h，day=近31天，month=近25个月，static=静态）。
     * tick = { pos(0-100), main, sub, major, majorLabel, align }
     */
    _buildTimeline: function (mode) {
      var now = new Date();
      var ticks = [];
      var i;
      var d;

      if (mode === 'hour') {
        for (i = 0; i < 48; i++) {
          d = new Date(now.getTime() + i * 3600 * 1000);
          var isNow = i === 0;
          var dayStart = d.getHours() === 0;
          ticks.push({
            pos: (i * 100) / 47,
            main: WEEK[d.getDay()] + ' ' + pad2(d.getHours()) + ':00',
            sub: (d.getMonth() + 1) + '月' + d.getDate() + '日 · ' + (isNow ? '现在' : '+' + i + 'h'),
            major: isNow || dayStart,
            majorLabel: isNow ? '现在' : dayStart ? (d.getMonth() + 1) + '/' + d.getDate() : '',
            align: i === 0 ? 'left' : i === 47 ? 'right' : 'center'
          });
        }
      } else if (mode === 'day') {
        for (i = 30; i >= 0; i--) {
          d = new Date(now.getTime() - i * 86400 * 1000);
          var isToday = i === 0;
          var monthStart = d.getDate() === 1;
          ticks.push({
            pos: ((30 - i) * 100) / 30,
            main: (d.getMonth() + 1) + '月' + d.getDate() + '日',
            sub: d.getFullYear() + '年 · ' + (isToday ? '今天' : '第' + (31 - i) + '/' + 31 + '天'),
            major: isToday || monthStart,
            majorLabel: isToday ? '今天' : monthStart ? (d.getMonth() + 1) + '月' : '',
            align: i === 30 ? 'left' : i === 0 ? 'right' : 'center'
          });
        }
      } else if (mode === 'month') {
        for (i = 24; i >= 0; i--) {
          d = new Date(now.getFullYear(), now.getMonth() - i, 1);
          var yearStart = d.getMonth() === 0;
          ticks.push({
            pos: ((24 - i) * 100) / 24,
            main: d.getFullYear() + '年' + (d.getMonth() + 1) + '月',
            sub: '月度数据 · ' + (24 - i + 1) + '/' + 25,
            major: yearStart || i === 24,
            majorLabel: yearStart ? d.getFullYear() + '年' : i === 24 ? '起点' : '',
            align: i === 24 ? 'left' : i === 0 ? 'right' : 'center'
          });
        }
      } else {
        // static
        ticks = [
          { pos: 0, main: '静态数据', sub: '该图层无时间维度', major: false, majorLabel: '', align: 'left' }
        ];
      }

      this.setData({ timeline: { mode: mode, ticks: ticks, current: 0 } });
    },

    /** 时间轴拖动 / 播放推进（M3 接瓦片刷新：hour→weather tiles，day/month→overlay tiles） */
    onTimelineChange: function (e) {
      var idx = e.detail.index;
      this.setData({ 'timeline.current': idx });
    },

    onTimelineToggle: function (e) {
      console.log('[map-shell] timeline playing =', e.detail.playing);
    },

    /** 点模式标签循环切换（M2 接图层选择前的演示入口） */
    onTimelineModeCycle: function () {
      var cur = this.data.timeline.mode;
      var next = TIMELINE_MODES[(TIMELINE_MODES.indexOf(cur) + 1) % TIMELINE_MODES.length];
      this._buildTimeline(next);
    },

    /** 调试/自动化入口：直接切换时间域 */
    demoTimeline: function (mode) {
      this._buildTimeline(mode);
      return { mode: mode, ticks: this.data.timeline.ticks.length };
    },

    /* ================= M0 自检 ================= */

    /**
     * M0 自检测试（spike 专用，M2 移除）：
     * 用 MapContext.getRegion 取视口 SW/NE 角（GCJ-02），经本组件 _project 投影后，
     * 应分别落在画布 (0,h) 与 (w,0)。误差（px）即「叠加层 vs 底图」对齐误差。
     * 结果写入 this._selfTestResult 并打到 HUD / console。
     */
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
          var hud = (self.data.debugHud || '') + '\nselftest errSW=' + result.errSWpx + 'px errNE=' + result.errNEpx + 'px';
          self.setData({ debugHud: hud });
        },
        fail: function (e) {
          self._selfTestResult = { fail: true, err: e };
        }
      });
      return { started: true };
    },

    _updateScaleBar: function () {
      var mpp = merc.metersPerPixel(this._centerGcj.lat, this._scale);
      this.setData({ metersPerPixel: mpp });
    },

    /** GCJ-02 经纬度 → 画布屏幕像素 */
    _project: function (latGcj, lngGcj) {
      var world = merc.worldSize(this._scale);
      var p = merc.project(lngGcj, latGcj, world);
      var c = merc.project(this._centerGcj.lng, this._centerGcj.lat, world);
      return { x: p.x - c.x + this._cv.w / 2, y: p.y - c.y + this._cv.h / 2 };
    },

    _drawOverlay: function (reason) {
      if (!this._cv || !this._centerGcj) {
        return;
      }
      var t0 = Date.now();
      var ctx = this._cv.ctx;
      var w = this._cv.w;
      var h = this._cv.h;
      ctx.clearRect(0, 0, w, h);

      // ---- 1) WGS-84 测试网格（±0.06°，步长 0.02°）：验证 GCJ02 纠偏 + mercator 对齐 ----
      var cWgs = gcj.gcj02ToWgs84(this._centerGcj.lng, this._centerGcj.lat);
      var pts = 0;
      ctx.font = '9px sans-serif';
      for (var dLat = -0.06; dLat <= 0.0601; dLat += 0.02) {
        for (var dLng = -0.06; dLng <= 0.0601; dLng += 0.02) {
          var wgsLat = cWgs.lat + dLat;
          var wgsLng = cWgs.lng + dLng;
          var g = gcj.wgs84ToGcj02(wgsLng, wgsLat);
          var s = this._project(g.lat, g.lng);
          if (s.x < -20 || s.x > w + 20 || s.y < -20 || s.y > h + 20) {
            continue;
          }
          ctx.beginPath();
          ctx.arc(s.x, s.y, 2.5, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(255, 87, 34, 0.9)';
          ctx.fill();
          ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
          ctx.fillText(wgsLat.toFixed(2) + ',' + wgsLng.toFixed(2), s.x + 4, s.y - 4);
          pts++;
        }
      }

      // ---- 2) 地标验证点：天安门（与 map marker 应重合）----
      var lmGcj = gcj.wgs84ToGcj02(LANDMARK_WGS.lng, LANDMARK_WGS.lat);
      var lm = this._project(lmGcj.lat, lmGcj.lng);
      ctx.beginPath();
      ctx.arc(lm.x, lm.y, 6, 0, Math.PI * 2);
      ctx.fillStyle = '#22a884';
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = '#ffffff';
      ctx.stroke();
      ctx.fillStyle = '#ffffff';
      ctx.font = '10px sans-serif';
      ctx.fillText('天安门 canvas', lm.x + 9, lm.y + 3);

      // ---- 3) 点击十字点 ----
      for (var i = 0; i < this._tapDots.length; i++) {
        var td = this._project(this._tapDots[i].lat, this._tapDots[i].lng);
        ctx.beginPath();
        ctx.moveTo(td.x - 7, td.y);
        ctx.lineTo(td.x + 7, td.y);
        ctx.moveTo(td.x, td.y - 7);
        ctx.lineTo(td.x, td.y + 7);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = '#378add';
        ctx.stroke();
      }

      // ---- 4) HUD ----
      var ms = Date.now() - t0;
      var mpp = merc.metersPerPixel(this._centerGcj.lat, this._scale);
      var hud =
        'M0 HUD (' + reason + ')\n' +
        'gcj ' + this._centerGcj.lng.toFixed(5) + ',' + this._centerGcj.lat.toFixed(5) + '\n' +
        'scale ' + this._scale.toFixed(2) + ' | ' + mpp.toFixed(1) + ' m/px\n' +
        'canvas ' + w + 'x' + h + ' @' + this._cv.dpr + 'x | ' + pts + 'pts | ' + ms + 'ms';
      this.setData({ debugHud: hud });
    }
  }
});
