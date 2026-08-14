// assets/charts.js — CGDA 前端设计调研报告图表
(function () {
  'use strict';

  // 从 CSS 变量读取主题色
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim() || '#3ab8d8';
  var accent2 = style.getPropertyValue('--accent2').trim() || '#e8965a';
  var ink = style.getPropertyValue('--ink').trim() || '#c8d6e5';
  var muted = style.getPropertyValue('--muted').trim() || '#6b8299';
  var rule = style.getPropertyValue('--rule').trim() || '#1a2d47';
  var bg2 = style.getPropertyValue('--bg2').trim() || '#0c1829';

  // 通用图表配置
  var baseTextStyle = {
    fontFamily: "'Outfit', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    color: muted,
  };

  // ==================== Chart 1: 设计成熟度雷达 ====================
  var radarDom = document.getElementById('chart-radar');
  if (radarDom) {
    var radarChart = echarts.init(radarDom, null, { renderer: 'canvas' });
    var radarOption = {
      textStyle: baseTextStyle,
      radar: {
        indicator: [
          { name: '令牌体系', max: 10 },
          { name: '组件一致性', max: 10 },
          { name: '响应式覆盖', max: 10 },
          { name: '动效克制性', max: 10 },
          { name: '无障碍', max: 10 },
          { name: '信息架构', max: 10 },
        ],
        shape: 'polygon',
        splitNumber: 5,
        axisName: {
          color: ink,
          fontSize: 12,
          fontFamily: baseTextStyle.fontFamily,
        },
        splitLine: { lineStyle: { color: rule } },
        splitArea: { areaStyle: { color: ['transparent', 'rgba(58,184,216,0.03)'] } },
        axisLine: { lineStyle: { color: rule } },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: [7.5, 4.5, 2.0, 5.5, 5.0, 5.0],
              name: 'CGDA 当前',
              lineStyle: { color: accent, width: 2 },
              areaStyle: { color: 'rgba(58,184,216,0.15)' },
              itemStyle: { color: accent },
              symbol: 'circle',
              symbolSize: 6,
            },
            {
              value: [9.0, 8.5, 7.0, 8.0, 8.5, 9.0],
              name: '行业标杆',
              lineStyle: { color: accent2, width: 2, type: 'dashed' },
              areaStyle: { color: 'rgba(232,150,90,0.08)' },
              itemStyle: { color: accent2 },
              symbol: 'circle',
              symbolSize: 5,
            },
          ],
        },
      ],
      legend: {
        bottom: 0,
        textStyle: { color: muted, fontFamily: baseTextStyle.fontFamily },
        itemWidth: 14,
        itemHeight: 8,
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: bg2,
        borderColor: rule,
        textStyle: { color: ink, fontFamily: baseTextStyle.fontFamily },
      },
    };
    radarChart.setOption(radarOption);
    window.addEventListener('resize', function () { radarChart.resize(); });
  }

  // ==================== Chart 2: 竞品功能对比 ====================
  var compDom = document.getElementById('chart-competitor');
  if (compDom) {
    var compChart = echarts.init(compDom, null, { renderer: 'canvas' });
    var categories = ['信息架构', '视觉语言', '交互模式', '响应式', '动效品质', '组件一致性'];
    var compOption = {
      textStyle: baseTextStyle,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: bg2,
        borderColor: rule,
        textStyle: { color: ink, fontFamily: baseTextStyle.fontFamily },
      },
      legend: {
        bottom: 0,
        textStyle: { color: muted, fontFamily: baseTextStyle.fontFamily, fontSize: 11 },
        itemWidth: 12,
        itemHeight: 8,
      },
      grid: { left: 80, right: 20, top: 20, bottom: 60 },
      xAxis: {
        type: 'value',
        max: 10,
        splitLine: { lineStyle: { color: rule, type: 'dashed' } },
        axisLabel: { color: muted, fontFamily: baseTextStyle.fontFamily },
        axisLine: { lineStyle: { color: rule } },
      },
      yAxis: {
        type: 'category',
        data: categories,
        axisLabel: { color: ink, fontFamily: baseTextStyle.fontFamily, fontSize: 11 },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false },
      },
      series: [
        {
          name: 'Windy',
          type: 'bar',
          barWidth: 6,
          data: [9, 9, 8, 5, 10, 7],
          itemStyle: { color: '#3ab8d8', borderRadius: [0, 3, 3, 0] },
        },
        {
          name: 'Google Earth',
          type: 'bar',
          barWidth: 6,
          data: [8, 8, 8, 6, 7, 8],
          itemStyle: { color: '#5ad5ff', borderRadius: [0, 3, 3, 0] },
        },
        {
          name: 'Kepler.gl',
          type: 'bar',
          barWidth: 6,
          data: [7, 7, 7, 4, 5, 6],
          itemStyle: { color: '#e8965a', borderRadius: [0, 3, 3, 0] },
        },
        {
          name: 'Mapbox Studio',
          type: 'bar',
          barWidth: 6,
          data: [8, 9, 9, 7, 8, 10],
          itemStyle: { color: '#9ff8cf', borderRadius: [0, 3, 3, 0] },
        },
        {
          name: 'CGDA 当前',
          type: 'bar',
          barWidth: 6,
          data: [5, 6, 5, 2, 5, 4],
          itemStyle: { color: '#ff8c64', borderRadius: [0, 3, 3, 0] },
        },
      ],
    };
    compChart.setOption(compOption);
    window.addEventListener('resize', function () { compChart.resize(); });
  }

  // ==================== Chart 3: 内联 Hex 分布 ====================
  var hexDom = document.getElementById('chart-hex-distribution');
  if (hexDom) {
    var hexChart = echarts.init(hexDom, null, { renderer: 'canvas' });
    var hexOption = {
      textStyle: baseTextStyle,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: bg2,
        borderColor: rule,
        textStyle: { color: ink, fontFamily: baseTextStyle.fontFamily },
        formatter: function (params) {
          var d = params[0];
          return d.name + '<br/>' + d.marker + ' ' + d.value + ' 个 hex 值';
        },
      },
      grid: { left: 160, right: 40, top: 10, bottom: 30 },
      xAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: rule, type: 'dashed' } },
        axisLabel: { color: muted, fontFamily: baseTextStyle.fontFamily },
        axisLine: { lineStyle: { color: rule } },
      },
      yAxis: {
        type: 'category',
        data: [
          'ModeToolbar.vue',
          'LayerSidebar.vue',
          'InfoPanel.vue',
          'TimelineScrubber.vue',
          'ControlPanel.vue',
          'MapCanvas.vue',
          '其他文件',
        ],
        inverse: true,
        axisLabel: {
          color: ink,
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
        },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          barWidth: 16,
          data: [
            { value: 62, itemStyle: { color: accent } },
            { value: 48, itemStyle: { color: accent } },
            { value: 38, itemStyle: { color: accent } },
            { value: 24, itemStyle: { color: 'rgba(58,184,216,0.7)' } },
            { value: 22, itemStyle: { color: 'rgba(58,184,216,0.7)' } },
            { value: 18, itemStyle: { color: 'rgba(58,184,216,0.5)' } },
            { value: 17, itemStyle: { color: 'rgba(58,184,216,0.4)' } },
          ],
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          label: {
            show: true,
            position: 'right',
            color: muted,
            fontFamily: baseTextStyle.fontFamily,
            fontSize: 11,
          },
        },
      ],
    };
    hexChart.setOption(hexOption);
    window.addEventListener('resize', function () { hexChart.resize(); });
  }

  // ==================== Chart 4: 实施路线图（甘特图） ====================
  var roadDom = document.getElementById('chart-roadmap');
  if (roadDom) {
    var roadChart = echarts.init(roadDom, null, { renderer: 'canvas' });
    var phases = ['S1 — 令牌补全', 'S2 — 基础组件库', 'S3 — 核心组件迁移', 'S4 — 响应式+验证'];
    var roadOption = {
      textStyle: baseTextStyle,
      tooltip: {
        trigger: 'item',
        backgroundColor: bg2,
        borderColor: rule,
        textStyle: { color: ink, fontFamily: baseTextStyle.fontFamily },
        formatter: function (params) {
          return params.name + '<br/>预估：' + params.value[1] + '–' + params.value[2] + ' 天';
        },
      },
      grid: { left: 150, right: 40, top: 20, bottom: 30 },
      xAxis: {
        type: 'value',
        min: 0,
        max: 35,
        name: '工作日',
        nameTextStyle: { color: muted, fontFamily: baseTextStyle.fontFamily },
        splitLine: { lineStyle: { color: rule, type: 'dashed' } },
        axisLabel: { color: muted, fontFamily: baseTextStyle.fontFamily },
        axisLine: { lineStyle: { color: rule } },
      },
      yAxis: {
        type: 'category',
        data: phases,
        inverse: true,
        axisLabel: { color: ink, fontFamily: baseTextStyle.fontFamily, fontSize: 12 },
        axisLine: { lineStyle: { color: rule } },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'custom',
          renderItem: function (params, api) {
            var catIdx = api.value(0);
            var start = api.coord([api.value(1), catIdx]);
            var end = api.coord([api.value(2), catIdx]);
            var height = api.size([0, 1])[1] * 0.5;
            var colors = [accent, '#5ad5ff', accent2, '#9ff8cf'];
            var rectShape = echarts.graphic.clipRectByRect(
              {
                x: start[0],
                y: start[1] - height / 2,
                width: end[0] - start[0],
                height: height,
              },
              {
                x: params.coordSys.x,
                y: params.coordSys.y,
                width: params.coordSys.width,
                height: params.coordSys.height,
              }
            );
            return (
              rectShape && {
                type: 'rect',
                transition: ['shape'],
                shape: rectShape,
                style: {
                  fill: colors[catIdx] || accent,
                  opacity: 0.85,
                },
                styleEmphasis: { opacity: 1 },
              }
            );
          },
          encode: { x: [1, 2], y: 0 },
          data: [
            { name: 'S1 — 令牌补全', value: [0, 0, 3] },
            { name: 'S2 — 基础组件库', value: [1, 3, 10] },
            { name: 'S3 — 核心组件迁移', value: [2, 8, 23] },
            { name: 'S4 — 响应式+验证', value: [3, 20, 27] },
          ],
        },
      ],
    };
    roadChart.setOption(roadOption);
    window.addEventListener('resize', function () { roadChart.resize(); });
  }
})();
