/**
 * timeline —— 底部横滑时间轴（Windy 式 4 层布局）。
 *
 * 4 层结构（wxml/wxss 承载，JS 不依赖）：
 *  - 第一层：头部控制栏（播放 + 主副标题 + 模式）
 *  - 第二层：间断日期标签（仅日期起始 tick 上方显示）
 *  - 第三层：水平基准圆点标线（贯穿虚线 + major/minor 圆点 + active 蓝）
 *  - 第四层：小时方框按钮（仅 major 渲染方框，active 实心蓝白字）
 *
 * 4 种时间域（mode）：
 *  - hour  逐小时（天气预报 hour 0-47）
 *  - day   逐日（SMAP/FY 等产品 time_list）
 *  - month 逐月（月度粒度图层）
 *  - static 静态图层（无时间维度，轨道收起）
 *
 * 4 条交互链路：
 *  - 拖动 scroll-view → 松手 200ms → _doSnap 吸附中心最近 tick → _setCurrent → change
 *  - 点击刻度 onTickTap → _setCurrent → change
 *  - 日历选日期 onCalDateSelect → _findTickIndexByDate → _jumpToIdx → _setCurrent
 *  - 播放按钮 onPlayTap → 700ms 循环 _setCurrent(next)
 *
 * 事件：
 *  - change({index})   选中变化
 *  - toggle({playing}) 播放切换
 *  - datejump({dateKey:'YYYY-MM-DD'})  日历快捷跳转
 *  - modecycle  模式循环
 */
var MODE_LABELS = {
  hour: '逐小时',
  day: '逐日',
  month: '逐月',
  static: '静态'
};
var PLAY_INTERVAL_MS = 700;
var SNAP_IDLE_MS = 200; // 滚动停止判定阈值（ms）
var BASE_TICK_W_PX = 42; // 每个 tick 默认像素宽度（适配后会用真实测量）

/* ============================================================
 * 工具函数：演示 ticks 回落 + 日历构建
 * ============================================================ */

/** 生成指定日期 00:00 起 N 小时的演示 ticks —— 无后端时回落
 *  startDate 可选，不传则用真实今天；dateHeader/main 的"今天/明天"判断始终基于真实今天 */
function buildFallbackTicks(count, startDate) {
  count = count || 48;
  var start = startDate ? new Date(startDate) : new Date();
  start.setHours(0, 0, 0, 0);

  var realToday = new Date();
  realToday.setHours(0, 0, 0, 0);
  var todayDateOnly = formatDateKey(realToday);
  var tomorrowDateOnly = formatDateKey(new Date(realToday.getTime() + 86400000));

  var result = [];
  var weekCN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  var lastDate = '';

  for (var i = 0; i < count; i++) {
    var d = new Date(start.getTime() + i * 3600 * 1000);
    var mm = d.getMonth() + 1 < 10 ? '0' + (d.getMonth() + 1) : '' + (d.getMonth() + 1);
    var dd = d.getDate() < 10 ? '0' + d.getDate() : '' + d.getDate();
    var hh = d.getHours() < 10 ? '0' + d.getHours() : '' + d.getHours();
    var timeKey = d.getFullYear() + '-' + mm + '-' + dd + 'T' + hh + ':00:00';
    var dateOnly = d.getFullYear() + '-' + mm + '-' + dd;

    var dateHeader = null;
    if (dateOnly !== lastDate) {
      var mShort = (d.getMonth() + 1);
      var dShort = d.getDate();
      var prefix = mShort + '月' + dShort + '号';
      dateHeader = prefix + weekCN[d.getDay()];
      lastDate = dateOnly;
    }

    var hourLabel = (d.getHours() < 10 ? '0' : '') + d.getHours();
    var isMajor = d.getHours() % 3 === 0;

    var mainText;
    if (dateOnly === todayDateOnly) {
      mainText = '今天 ' + hh + ':00';
    } else if (dateOnly === tomorrowDateOnly) {
      mainText = '明天 ' + hh + ':00';
    } else {
      mainText = (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hh + ':00';
    }

    result.push({
      main: mainText,
      sub: dateOnly,
      major: isMajor,
      majorLabel: isMajor ? hourLabel : '',
      align: 'center',
      timeKey: timeKey,
      dateOnly: dateOnly,
      dateHeader: dateHeader
    });
  }
  return result;
}

function formatDateKey(d) {
  var mm = d.getMonth() + 1 < 10 ? '0' + (d.getMonth() + 1) : '' + (d.getMonth() + 1);
  var dd = d.getDate() < 10 ? '0' + d.getDate() : '' + d.getDate();
  return d.getFullYear() + '-' + mm + '-' + dd;
}

/* ---------- 日历三层构建 ---------- */

function makeDateCell(y, m, d, inMonth, todayKey, selectedKey) {
  var mm = (m + 1) < 10 ? '0' + (m + 1) : '' + (m + 1);
  var dd = d < 10 ? '0' + d : d;
  var key = y + '-' + mm + '-' + dd;
  return {
    day: d,
    dateKey: key,
    inMonth: inMonth,
    isToday: key === todayKey,
    isSelected: key === selectedKey
  };
}

/** 构建一个月的日期网格（6 行 7 列）：含上月/下月溢出日期 */
function buildMonthGrid(year, month, selectedDateKey) {
  var first = new Date(year, month, 1);
  var startOffset = first.getDay();
  var daysInMonth = new Date(year, month + 1, 0).getDate();
  var prevMonthDays = new Date(year, month, 0).getDate();
  var todayKey = formatDateKey(new Date());

  var rows = [];
  var cells = [];

  var offset = (startOffset - 1 + 7) % 7;

  for (var i = 0; i < offset; i++) {
    var pd = prevMonthDays - offset + 1 + i;
    var prevMonth = month === 0 ? 11 : month - 1;
    var prevYear = month === 0 ? year - 1 : year;
    cells.push(makeDateCell(prevYear, prevMonth, pd, false, todayKey, selectedDateKey));
  }

  for (var d = 1; d <= daysInMonth; d++) {
    cells.push(makeDateCell(year, month, d, true, todayKey, selectedDateKey));
    if (cells.length === 7) {
      rows.push(cells);
      cells = [];
    }
  }

  var nextMonth = month === 11 ? 0 : month + 1;
  var nextYear = month === 11 ? year + 1 : year;
  var nd = 1;
  while (cells.length < 7) {
    cells.push(makeDateCell(nextYear, nextMonth, nd, false, todayKey, selectedDateKey));
    nd++;
  }
  if (cells.length) rows.push(cells);
  while (rows.length < 6) {
    var lastRow = [];
    for (var j = 0; j < 7; j++) {
      lastRow.push(makeDateCell(nextYear, nextMonth, nd, false, todayKey, selectedDateKey));
      nd++;
    }
    rows.push(lastRow);
  }
  return rows;
}

function buildMonthPickerGrid(selectedMonth) {
  var labels = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月'];
  var rows = [[], [], []];
  for (var i = 0; i < 12; i++) {
    rows[Math.floor(i / 4)].push({
      month: i,
      label: labels[i],
      isCurrent: i === selectedMonth
    });
  }
  return rows;
}

function buildYearPickerGrid(decadeStart, selectedYear) {
  var rows = [[], []];
  for (var i = 0; i < 10; i++) {
    var y = decadeStart + i;
    rows[Math.floor(i / 5)].push({
      year: y,
      isCurrent: y === selectedYear
    });
  }
  return rows;
}

/* ============================================================
 * 组件定义
 * ============================================================ */

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  properties: {
    mode: { type: String, value: 'static' },
    ticks: { type: Array, value: [] },
    current: { type: Number, value: 0 },
    timezone: { type: String, value: '' },
    // 外部传入：让 timeline 跳到此日期（YYYY-MM-DD）；父级 set → 内部消费后清空，防重复
    targetDateKey: { type: String, value: '' }
  },

  data: {
    // 业务状态
    playing: false,
    mainLabel: '',
    subLabel: '',
    modeLabel: '静态',
    timezoneLabel: '',

    // 折叠状态
    collapsed: false,

    // 演示回落
    displayTicks: [],
    displayMode: 'static',
    displayCurrent: 0,
    isFallback: false,

    // scroll-view 滚动吸附
    scrollLeft: 0,
    scrollWithAnim: true,

    // 日历弹层（保留备用，本次 wxml 不绑定）
    calendarOpen: false,
    calendarView: 'month',
    calendarYear: 0,
    calendarMonth: 0,
    calendarHeader: '',
    calendarDecadeStart: 0,
    calendarRows: [],
    monthPickerRows: [],
    yearPickerRows: [],
    selectedDateKey: ''
  },

  observers: {
    'mode, ticks, current, timezone': function () {
      this._refresh();
    },
    // displayTicks 变（粒度切换/回落）→ DOM 渲染后重测真实 tick 宽度
    displayTicks: function () {
      var self = this;
      setTimeout(function () {
        self._measureSizes();
      }, 0);
    },
    // 外部传入 targetDateKey → 内部找对应 tick 跳
    targetDateKey: function (key) {
      if (!key) return;
      var idx = this._findTickIndexByDate(key);
      if (idx >= 0) {
        this._jumpToIdx(idx, true);
      }
      this.setData({ targetDateKey: '' });
    }
  },

  lifetimes: {
    ready: function () {
      this._measureSizes();
      // 初始上报一次高度，让父级的 HUD/比例尺位置同步
      var self = this;
      setTimeout(function () {
        var q = self.createSelectorQuery();
        q.select('.tl').boundingClientRect(function (r) {
          var h = r ? r.height : 128;
          self.triggerEvent('collapse', { collapsed: self.data.collapsed, height: h });
        });
        q.exec();
      }, 50);
    },
    detached: function () {
      this._stopTimer();
      if (this._snapTimer) clearTimeout(this._snapTimer);
    }
  },

  methods: {
    _measureSizes: function () {
      var self = this;
      var N = (this.data.displayTicks || []).length;
      var q = this.createSelectorQuery();
      q.select('.tl-viewport').boundingClientRect(function (vp) {
        if (vp) self._viewportW = vp.width;
      });
      if (N > 0) {
        q.select('.tl-content').boundingClientRect(function (ct) {
          if (ct && ct.width > 0) {
            self._tickW = ct.width / N;
          }
        });
      }
      q.exec();
    },

    _refresh: function () {
      var ticks = this.properties.ticks || [];
      var mode = this.properties.mode;
      var cur = this.properties.current;
      var tz = this.properties.timezone || '';
      var fallback = false;

      if ((mode === 'static' || mode === undefined) && (!ticks || ticks.length === 0)) {
        ticks = buildFallbackTicks(48);
        mode = 'hour';
        var now = new Date();
        cur = Math.min(now.getHours(), ticks.length - 1);
        fallback = true;
      }

      if (this._lastMode !== undefined && this._lastMode !== mode) {
        this._stopTimer();
      }
      this._lastMode = mode;

      var item = ticks[cur] || {};
      var self = this;
      var mainText, subText;

      if (fallback) {
        // 进入时同步显示当前真实时间（含分钟），不是固定文本
        var nowFmt = new Date();
        var hhFmt = nowFmt.getHours() < 10 ? '0' + nowFmt.getHours() : '' + nowFmt.getHours();
        var mmFmt = nowFmt.getMinutes() < 10 ? '0' + nowFmt.getMinutes() : '' + nowFmt.getMinutes();
        mainText = '今天 ' + hhFmt + ':' + mmFmt;
        subText = formatDateKey(nowFmt);
      } else {
        mainText = item.main || '';
        subText = item.sub || '';
      }

      this.setData({
        mainLabel: mainText,
        subLabel: subText,
        modeLabel: MODE_LABELS[mode] || mode,
        timezoneLabel: tz,
        displayTicks: ticks,
        displayMode: mode,
        displayCurrent: cur,
        isFallback: fallback
      }, function () {
        setTimeout(function () {
          self._measureSizes();
          self._scrollToCurrent(false);
        }, 0);
      });
    },

    _setCurrent: function (idx) {
      if (idx === this.data.displayCurrent) {
        this._scrollToCurrent(idx, true);
        return;
      }
      if (this.data.isFallback) {
        var ticks = this.data.displayTicks;
        var item = ticks[idx] || {};
        this.setData({ displayCurrent: idx, mainLabel: item.main || '', subLabel: item.sub || '' });
        this._scrollToCurrent(idx, true);
      } else {
        this.triggerEvent('change', { index: idx });
      }
    },

    /* ================ 工具：按 dateKey 找 tick 索引 + 程序跳转 ================ */

    _findTickIndexByDate: function (dateKey) {
      if (!dateKey) return -1;
      var ticks = this.data.displayTicks || [];
      for (var i = 0; i < ticks.length; i++) {
        var t = ticks[i];
        var d = t.dateOnly || (t.timeKey ? t.timeKey.substring(0, 10) : null);
        if (d === dateKey) return i;
      }
      return -1;
    },

    _jumpToIdx: function (idx, anim) {
      var N = (this.data.displayTicks || []).length;
      if (idx < 0 || idx >= N) return;
      this._scrollToCurrent(idx, !!anim);
      this._setCurrent(idx);
    },

    /* ================ scroll-view 吸附对齐 ================ */

    onScroll: function (e) {
      this._lastScrollLeft = e.detail.scrollLeft;
      this._viewportW = e.detail.scrollWidth ? this._viewportW : undefined;
      clearTimeout(this._snapTimer);
      var self = this;
      this._snapTimer = setTimeout(function () {
        self._doSnap();
      }, SNAP_IDLE_MS);
    },

    _doSnap: function () {
      // 程序跳转（点击/播放/日历跳转）触发的滚动不吸附，避免覆盖用户选择
      if (this._skipSnap) {
        this._skipSnap = false;
        return;
      }
      var N = this.data.displayTicks.length;
      if (!N) return;
      if (!this._tickW) this._measureSizes();
      var tickW = this._tickW || BASE_TICK_W_PX;
      var vpW = this._viewportW || 340;
      var sL0 = this._lastScrollLeft || 0;
      // 无 padding 布局：scrollLeft + vpW/2 = idx*tickW + tickW/2
      var idx = Math.round((sL0 + vpW / 2 - tickW / 2) / tickW);
      idx = Math.max(0, Math.min(N - 1, idx));
      var targetSL = idx * tickW - (vpW - tickW) / 2;
      var maxSL = N * tickW - vpW;
      if (maxSL < 0) maxSL = 0;
      targetSL = Math.max(0, Math.min(maxSL, targetSL));
      var self = this;
      this.setData({ scrollLeft: targetSL, scrollWithAnim: true }, function () {
        setTimeout(function () {
          self.setData({ scrollWithAnim: false });
        }, 250);
      });
      if (idx !== this.data.displayCurrent) {
        this._setCurrent(idx);
      }
    },

    _scrollToCurrent: function (idxOrAnim, animOnlyWhenIdx) {
      var N = this.data.displayTicks.length;
      if (!N) return;
      var idx, anim;
      if (typeof idxOrAnim === 'number') {
        idx = idxOrAnim;
        anim = !!animOnlyWhenIdx;
      } else {
        idx = this.data.displayCurrent;
        anim = !!idxOrAnim;
      }
      idx = Math.max(0, Math.min(N - 1, idx));
      if (!this._tickW) this._measureSizes();
      var tickW = this._tickW || BASE_TICK_W_PX;
      var vpW = this._viewportW || 340;
      var targetSL = idx * tickW - (vpW - tickW) / 2;
      var maxSL = N * tickW - vpW;
      if (maxSL < 0) maxSL = 0;
      targetSL = Math.max(0, Math.min(maxSL, targetSL));
      // 标记程序跳转，_doSnap 跳过本次吸附
      this._skipSnap = true;
      var self = this;
      this.setData({ scrollLeft: targetSL, scrollWithAnim: anim }, function () {
        if (anim) {
          setTimeout(function () {
            self.setData({ scrollWithAnim: false });
          }, 250);
        }
      });
    },

    /* ================ 播放 ================ */

    onPlayTap: function () {
      var mode = this.data.displayMode;
      if (mode === 'static') return;
      if (this.data.playing) {
        this._stopTimer();
        this.setData({ playing: false });
        this.triggerEvent('toggle', { playing: false });
      } else {
        var self = this;
        this._timer = setInterval(function () {
          var ticks = self.data.displayTicks;
          var n = ticks.length;
          if (!n) return;
          var cur = self.data.displayCurrent;
          var next = (cur + 1) % n;
          self._setCurrent(next);
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

    /* ================ 折叠/展开 ================ */

    onToggleCollapse: function () {
      var next = !this.data.collapsed;
      var self = this;
      this.setData({ collapsed: next }, function () {
        if (next && self.data.playing) {
          self._stopTimer();
          self.setData({ playing: false });
          self.triggerEvent('toggle', { playing: false });
        }
        // 通知父级：折叠状态变化 + 真实占用高度
        var q = self.createSelectorQuery();
        q.select('.tl').boundingClientRect(function (r) {
          var h = r ? r.height : (next ? 20 : 128);
          self.triggerEvent('collapse', { collapsed: next, height: h });
        });
        q.exec();
      });
    },

    /* ================ 点击刻度 ================ */

    onTickTap: function (e) {
      var mode = this.data.displayMode;
      if (mode === 'static') return;
      var idx = e.currentTarget.dataset.index;
      if (idx !== undefined) {
        this._setCurrent(idx);
      }
    },

    /* ================ 日历三层弹窗（保留备用，本次 wxml 不绑定） ================ */

    onCalendarTap: function () {
      var mode = this.data.displayMode;
      if (mode === 'static') return;
      var y, m;
      if (this.data.calendarYear === 0) {
        var now = new Date();
        y = now.getFullYear();
        m = now.getMonth();
      } else {
        y = this.data.calendarYear;
        m = this.data.calendarMonth;
      }
      var selKey = this.data.selectedDateKey || formatDateKey(new Date());
      this._openCalendar(y, m, selKey, 'month');
    },

    _openCalendar: function (y, m, selKey, view) {
      var header = y + ' 年 ' + (m + 1) + ' 月';
      var decadeStart = Math.floor(y / 10) * 10;
      this.setData({
        calendarOpen: true,
        calendarView: view,
        calendarYear: y,
        calendarMonth: m,
        calendarHeader: header,
        calendarDecadeStart: decadeStart,
        calendarRows: buildMonthGrid(y, m, selKey),
        monthPickerRows: buildMonthPickerGrid(m),
        yearPickerRows: buildYearPickerGrid(decadeStart, y),
        selectedDateKey: selKey
      });
    },

    onCalendarClose: function () {
      this.setData({ calendarOpen: false });
    },
    onCalendarStop: function () {},

    onCalPrevMonth: function () {
      var y = this.data.calendarYear;
      var m = this.data.calendarMonth - 1;
      if (m < 0) { m = 11; y--; }
      this._openCalendar(y, m, this.data.selectedDateKey, 'month');
    },
    onCalNextMonth: function () {
      var y = this.data.calendarYear;
      var m = this.data.calendarMonth + 1;
      if (m > 11) { m = 0; y++; }
      this._openCalendar(y, m, this.data.selectedDateKey, 'month');
    },
    onCalYearClick: function () {
      this.setData({
        calendarView: 'monthPicker',
        calendarHeader: '' + this.data.calendarYear,
        monthPickerRows: buildMonthPickerGrid(this.data.calendarMonth)
      });
    },
    onCalDateSelect: function (e) {
      var key = e.currentTarget.dataset.key;
      if (!key) return;

      // 解析选中的日期
      var parts = key.split('-');
      var y = parseInt(parts[0], 10);
      var mm = parseInt(parts[1], 10);
      var dd = parseInt(parts[2], 10);
      var selDate = new Date(y, mm - 1, dd);

      // 重新生成从选中日期起的 48 小时 ticks（dateHeader 会跟着变）
      var newTicks = buildFallbackTicks(48, selDate);

      // 保留当前选中的刻度（小时不变，不跳刻度）
      var cur = this.data.displayCurrent;
      var newCur = Math.min(cur, newTicks.length - 1);
      var curMain = (newTicks[newCur] && newTicks[newCur].main) || '';

      this.setData({
        calendarOpen: false,
        selectedDateKey: key,
        displayTicks: newTicks,
        displayCurrent: newCur,
        mainLabel: curMain,
        subLabel: key
      });

      // DOM 渲染后重新测量 + 滚到当前刻度
      var self = this;
      setTimeout(function () {
        self._measureSizes();
        self._scrollToCurrent(newCur, false);
      }, 0);

      this.triggerEvent('datejump', { dateKey: key });
    },

    onCalPrevYear: function () {
      var y = this.data.calendarYear - 1;
      var m = this.data.calendarMonth;
      this.setData({
        calendarYear: y,
        calendarHeader: '' + y,
        monthPickerRows: buildMonthPickerGrid(m)
      });
    },
    onCalNextYear: function () {
      var y = this.data.calendarYear + 1;
      var m = this.data.calendarMonth;
      this.setData({
        calendarYear: y,
        calendarHeader: '' + y,
        monthPickerRows: buildMonthPickerGrid(m)
      });
    },
    onCalPickYearClick: function () {
      var y = this.data.calendarYear;
      var decadeStart = Math.floor(y / 10) * 10;
      this.setData({
        calendarView: 'yearPicker',
        calendarDecadeStart: decadeStart,
        calendarHeader: decadeStart + ' - ' + (decadeStart + 9),
        yearPickerRows: buildYearPickerGrid(decadeStart, y)
      });
    },
    onCalMonthPick: function (e) {
      var m = e.currentTarget.dataset.month;
      var y = this.data.calendarYear;
      this._openCalendar(y, m, this.data.selectedDateKey, 'month');
    },

    onCalPrevDecade: function () {
      var ds = this.data.calendarDecadeStart - 10;
      var y = this.data.calendarYear;
      this.setData({
        calendarDecadeStart: ds,
        calendarHeader: ds + ' - ' + (ds + 9),
        yearPickerRows: buildYearPickerGrid(ds, y)
      });
    },
    onCalNextDecade: function () {
      var ds = this.data.calendarDecadeStart + 10;
      var y = this.data.calendarYear;
      this.setData({
        calendarDecadeStart: ds,
        calendarHeader: ds + ' - ' + (ds + 9),
        yearPickerRows: buildYearPickerGrid(ds, y)
      });
    },
    onCalYearPick: function (e) {
      var y = e.currentTarget.dataset.year;
      var m = this.data.calendarMonth;
      this.setData({
        calendarView: 'monthPicker',
        calendarYear: y,
        calendarHeader: '' + y,
        monthPickerRows: buildMonthPickerGrid(m)
      });
    }
  }
});
