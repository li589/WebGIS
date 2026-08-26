/**
 * date-strip —— 横向滑动日期选择条。
 *
 * 中间是今天日期，两边是前一天 / 后一天，共 61 天（前后各 30 天）。
 * 横向滑动 → 松手 200ms → 吸附对齐中心最近 cell → 更新 currentIdx。
 * 点击 cell → 滚到中心 + 高亮。
 *
 * 事件：
 *  - change({dateKey:'YYYY-MM-DD'})  选中日期变化
 *
 * 布局铁律：
 *  - 复用 timeline 已验证的 padding-left/right:50% + 吸附公式
 *  - scrollLeft = idx * cellW + cellW / 2
 *  - idx吸附 = round((sL0 - cellW/2) / cellW)
 */
var WEEKDAYS_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
var MONTHS_SHORT = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'];
var SNAP_IDLE_MS = 200;
var CELL_W_PX = 60;
var BASE_VIEWPORT_W = 340;

function formatDateKey(d) {
  var mm = d.getMonth() + 1 < 10 ? '0' + (d.getMonth() + 1) : '' + (d.getMonth() + 1);
  var dd = d.getDate() < 10 ? '0' + d.getDate() : d.getDate();
  return d.getFullYear() + '-' + mm + '-' + dd;
}

function buildDates(centerDate, range) {
  range = range || 30;
  var todayKey = formatDateKey(new Date());
  var result = [];
  for (var i = -range; i <= range; i++) {
    var d = new Date(centerDate.getTime() + i * 86400000);
    result.push({
      key: formatDateKey(d),
      year: d.getFullYear(),
      month: d.getMonth() + 1,
      day: d.getDate(),
      weekdayShort: WEEKDAYS_CN[d.getDay()],
      monthShort: MONTHS_SHORT[d.getMonth()],
      isToday: formatDateKey(d) === todayKey
    });
  }
  return result;
}

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    dates: [],
    currentIdx: 0,
    scrollLeft: 0,
    scrollWithAnim: false
  },

  lifetimes: {
    ready: function () {
      this._init();
    },
    detached: function () {
      if (this._snapTimer) clearTimeout(this._snapTimer);
    }
  },

  methods: {
    _measureSizes: function () {
      var self = this;
      var q = this.createSelectorQuery();
      q.select('.ds-viewport').boundingClientRect(function (vp) {
        if (vp && vp.width > 0) self._viewportW = vp.width;
      });
      q.exec();
    },

    _init: function () {
      var today = new Date();
      today.setHours(0, 0, 0, 0);
      var dates = buildDates(today, 30);
      var self = this;
      this.setData({
        dates: dates,
        currentIdx: 30
      }, function () {
        setTimeout(function () {
          self._measureSizes();
          self._scrollToIdx(30, false);
        }, 0);
      });
    },

    onScroll: function (e) {
      this._lastScrollLeft = e.detail.scrollLeft;
      clearTimeout(this._snapTimer);
      var self = this;
      this._snapTimer = setTimeout(function () {
        self._doSnap();
      }, SNAP_IDLE_MS);
    },

    _doSnap: function () {
      var N = this.data.dates.length;
      if (!N) return;
      var cellW = CELL_W_PX;
      var vpW = this._viewportW || BASE_VIEWPORT_W;
      var sL0 = this._lastScrollLeft || 0;
      // 无 padding 布局：scrollLeft + vpW/2 = idx*cellW + cellW/2
      var idx = Math.round((sL0 + vpW / 2 - cellW / 2) / cellW);
      idx = Math.max(0, Math.min(N - 1, idx));
      var targetSL = idx * cellW - (vpW - cellW) / 2;
      var maxSL = N * cellW - vpW;
      if (maxSL < 0) maxSL = 0;
      targetSL = Math.max(0, Math.min(maxSL, targetSL));
      var self = this;
      this.setData({ scrollLeft: targetSL, scrollWithAnim: true }, function () {
        setTimeout(function () {
          self.setData({ scrollWithAnim: false });
        }, 250);
      });
      if (idx !== this.data.currentIdx) {
        this.setData({ currentIdx: idx });
        this.triggerEvent('change', { dateKey: this.data.dates[idx].key });
      }
    },

    _scrollToIdx: function (idx, anim) {
      var N = this.data.dates.length;
      if (!N) return;
      idx = Math.max(0, Math.min(N - 1, idx));
      var cellW = CELL_W_PX;
      var vpW = this._viewportW || BASE_VIEWPORT_W;
      var targetSL = idx * cellW - (vpW - cellW) / 2;
      var maxSL = N * cellW - vpW;
      if (maxSL < 0) maxSL = 0;
      targetSL = Math.max(0, Math.min(maxSL, targetSL));
      var self = this;
      this.setData({ scrollLeft: targetSL, scrollWithAnim: anim }, function () {
        if (anim) {
          setTimeout(function () {
            self.setData({ scrollWithAnim: false });
          }, 250);
        }
      });
    },

    onCellTap: function (e) {
      var idx = e.currentTarget.dataset.index;
      if (idx === undefined) return;
      var self = this;
      this.setData({ currentIdx: idx });
      this._scrollToIdx(idx, true);
      this.triggerEvent('change', { dateKey: this.data.dates[idx].key });
    }
  }
});
