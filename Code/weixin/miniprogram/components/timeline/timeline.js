/**
 * timeline —— 底部全宽时间轴（Windy 式）。
 *
 * 四种时间域（mode）：
 *  - hour  逐小时（天气预报 hour 0-47）
 *  - day   逐日（SMAP/FY 等产品 time_list）
 *  - month 逐月（月度粒度图层）
 *  - static 静态图层（无时间维度，轨道收起）
 *
 * 组件保持「哑」：ticks / current 由父级（map-shell）下发，
 * 每个 tick = { pos(0-100), main, sub, major, majorLabel, align }。
 * 事件：change({index})（拖动/播放推进）、toggle({playing})、modecycle()（点模式标签切换，M2 接图层前演示用）。
 */
var MODE_LABELS = {
  hour: '逐小时',
  day: '逐日',
  month: '逐月',
  static: '静态'
};
var PLAY_INTERVAL_MS = 700;

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  properties: {
    mode: {
      type: String,
      value: 'static'
    },
    ticks: {
      type: Array,
      value: []
    },
    current: {
      type: Number,
      value: 0
    }
  },

  data: {
    playing: false,
    mainLabel: '',
    subLabel: '',
    modeLabel: '静态',
    pct: 0
  },

  observers: {
    'mode, ticks, current': function () {
      this._refresh();
    }
  },

  lifetimes: {
    ready: function () {
      var self = this;
      this.createSelectorQuery()
        .select('.tl-track')
        .boundingClientRect(function (rect) {
          if (rect) {
            self._rect = rect;
          }
        })
        .exec();
    },
    detached: function () {
      this._stopTimer();
    }
  },

  methods: {
    _refresh: function () {
      var ticks = this.properties.ticks || [];
      var mode = this.properties.mode;
      var cur = this.properties.current;
      var item = ticks[cur] || {};

      // 模式切换时停止播放
      if (this._lastMode !== undefined && this._lastMode !== mode) {
        this._stopTimer();
      }
      this._lastMode = mode;

      var pct = ticks.length > 1 ? (cur / (ticks.length - 1)) * 100 : 0;
      this.setData({
        mainLabel: item.main || '',
        subLabel: item.sub || '',
        modeLabel: MODE_LABELS[mode] || mode,
        pct: pct
      });
    },

    onPlayTap: function () {
      if (this.properties.mode === 'static') {
        return;
      }
      if (this.data.playing) {
        this._stopTimer();
        this.setData({ playing: false });
        this.triggerEvent('toggle', { playing: false });
      } else {
        var self = this;
        this._timer = setInterval(function () {
          var n = self.properties.ticks.length;
          if (!n) {
            return;
          }
          var next = (self.properties.current + 1) % n;
          self.triggerEvent('change', { index: next });
        }, PLAY_INTERVAL_MS);
        this.setData({ playing: true });
        this.triggerEvent('toggle', { playing: true });
      }
    },

    _stopTimer: function () {
      if (this._timer) {
        clearInterval(this._timer);
        this._timer = null;
      }
    },

    onModeTap: function () {
      this.triggerEvent('modecycle');
    },

    /** 轨道拖动：clientX → 最近 tick 索引（吸附） */
    onTrackTouch: function (e) {
      if (this.properties.mode === 'static') {
        return;
      }
      var ticks = this.properties.ticks;
      if (!this._rect || !ticks.length) {
        return;
      }
      var t = e.touches && e.touches[0];
      if (!t) {
        return;
      }
      var x = t.clientX - this._rect.left;
      var n = ticks.length;
      var idx = Math.round((x / this._rect.width) * (n - 1));
      idx = Math.max(0, Math.min(n - 1, idx));
      if (idx !== this.properties.current) {
        this.triggerEvent('change', { index: idx });
      }
    }
  }
});
