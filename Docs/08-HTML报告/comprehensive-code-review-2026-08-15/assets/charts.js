(function() {
  var style = getComputedStyle(document.documentElement);
  var accent = style.getPropertyValue('--accent').trim();
  var accent2 = style.getPropertyValue('--accent2').trim();
  var ink = style.getPropertyValue('--ink').trim();
  var muted = style.getPropertyValue('--muted').trim();
  var rule = style.getPropertyValue('--rule').trim();
  var bg2 = style.getPropertyValue('--bg2').trim();
  var ok = style.getPropertyValue('--ok').trim();
  var warn = style.getPropertyValue('--warn').trim();

  var el1 = document.getElementById('chart-regress');
  if (el1) {
    var c1 = echarts.init(el1, null, { renderer: 'svg' });
    c1.setOption({
      animation: false,
      grid: { left: 110, right: 30, top: 34, bottom: 28 },
      legend: { top: 0, textStyle: { color: ink, fontSize: 12 } },
      tooltip: { trigger: 'axis', appendToBody: true },
      xAxis: {
        type: 'value',
        minInterval: 1,
        axisLabel: { color: muted },
        splitLine: { lineStyle: { color: rule } }
      },
      yAxis: {
        type: 'category',
        data: ['后端 failed', '后端 errors', '算法 failed', '前端未跑文件'],
        axisLabel: { color: ink, fontSize: 12 },
        axisLine: { lineStyle: { color: rule } }
      },
      series: [
        {
          name: '基线（T1）',
          type: 'bar',
          data: [13, 12, 0, 0],
          itemStyle: { color: accent2 },
          barWidth: 18,
          label: { show: true, position: 'right', color: ink, fontSize: 11 }
        },
        {
          name: '终态（T11 / R2 复验）',
          type: 'bar',
          data: [0, 0, 0, 10],
          itemStyle: { color: accent },
          barWidth: 18,
          label: {
            show: true,
            position: 'right',
            color: ink,
            fontSize: 11,
            formatter: function(p) {
              return p.value === 10 ? '10 → 单独批次验证 0 失败' : String(p.value);
            }
          }
        }
      ]
    });
    window.addEventListener('resize', function() { c1.resize(); });
  }

  var el2 = document.getElementById('chart-legacy');
  if (el2) {
    var c2 = echarts.init(el2, null, { renderer: 'svg' });
    c2.setOption({
      animation: false,
      tooltip: { trigger: 'item', appendToBody: true },
      legend: { orient: 'vertical', right: 8, top: 'center', textStyle: { color: ink, fontSize: 12 } },
      series: [
        {
          name: '遗留终态',
          type: 'pie',
          radius: ['42%', '68%'],
          center: ['38%', '52%'],
          label: { color: ink, fontSize: 12, formatter: '{b}\n{c} 项' },
          data: [
            { value: 9, name: '闭环（含 2 项部分）', itemStyle: { color: ok } },
            { value: 4, name: '仍存在（并入留痕）', itemStyle: { color: accent2 } },
            { value: 2, name: '未复检（N-11/N-12）', itemStyle: { color: warn } }
          ]
        }
      ]
    });
    window.addEventListener('resize', function() { c2.resize(); });
  }
})();
