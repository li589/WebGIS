// assets/charts.js - Security Upgrade Summary Charts
(function () {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();

  // --- Chart: Changes by Phase ---
  var chart1 = echarts.init(document.getElementById('chart-phase-effort'), null, { renderer: 'svg' });
  chart1.setOption({
    tooltip: { trigger: 'axis', appendToBody: true },
    animation: false,
    grid: { left: 80, right: 30, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: ['Phase A\n契约同步', 'Phase B\n资源访问控制', 'Phase C\n并发控制', 'Phase D\n前端适配'],
      axisLabel: { color: muted, fontSize: 12 },
      axisLine: { lineStyle: { color: rule } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: '变更行数',
      nameTextStyle: { color: muted, fontSize: 11 },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } },
    },
    series: [
      {
        type: 'bar',
        data: [180, 680, 380, 320],
        itemStyle: {
          color: function (p) {
            var colors = [accent, accent2, accent, accent2];
            return colors[p.dataIndex];
          },
          borderRadius: [4, 4, 0, 0],
        },
        barWidth: '45%',
        label: {
          show: true,
          position: 'top',
          color: ink,
          fontWeight: 600,
          fontSize: 13,
          formatter: function (p) { return p.value + '行'; },
        },
      },
    ],
  });
  window.addEventListener('resize', function () { chart1.resize(); });

  // --- Chart: Verification Results ---
  var chart2 = echarts.init(document.getElementById('chart-verification'), null, { renderer: 'svg' });
  chart2.setOption({
    tooltip: { trigger: 'item', appendToBody: true },
    animation: false,
    legend: {
      bottom: 0,
      textStyle: { color: muted, fontSize: 12 },
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '45%'],
        avoidLabelOverlap: true,
        itemStyle: { borderRadius: 6, borderColor: bg2, borderWidth: 2 },
        label: { show: true, formatter: '{b}\n{c}', color: ink, fontSize: 12, fontWeight: 600 },
        emphasis: { label: { show: true, fontWeight: 'bold' } },
        data: [
          { value: 41, name: '后端测试', itemStyle: { color: accent } },
          { value: 636, name: '前端测试', itemStyle: { color: accent2 } },
          { value: 0, name: 'Lint 错误', itemStyle: { color: muted } },
          { value: 1, name: 'Build 成功', itemStyle: { color: '#4caf50' } },
          { value: 1, name: 'OpenAPI 校验', itemStyle: { color: '#ff9800' } },
        ],
      },
    ],
  });
  window.addEventListener('resize', function () { chart2.resize(); });

  // --- Chart: File Distribution ---
  var chart3 = echarts.init(document.getElementById('chart-file-dist'), null, { renderer: 'svg' });
  chart3.setOption({
    tooltip: { trigger: 'axis', appendToBody: true },
    animation: false,
    grid: { left: 100, right: 30, top: 20, bottom: 30 },
    xAxis: {
      type: 'value',
      name: '修改文件数',
      nameTextStyle: { color: muted, fontSize: 11 },
      axisLabel: { color: muted },
      splitLine: { lineStyle: { color: rule, type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: ['后端 Python', '前端 Vue/TS', '测试', '前端契约', '配置文件'],
      axisLabel: { color: ink, fontSize: 12, fontWeight: 600 },
      axisLine: { lineStyle: { color: rule } },
      axisTick: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: [16, 5, 4, 2, 1],
        itemStyle: {
          color: accent,
          borderRadius: [0, 4, 4, 0],
        },
        barWidth: '55%',
        label: {
          show: true,
          position: 'right',
          color: ink,
          fontWeight: 600,
          formatter: function (p) { return p.value + '个'; },
        },
      },
    ],
  });
  window.addEventListener('resize', function () { chart3.resize(); });
})();