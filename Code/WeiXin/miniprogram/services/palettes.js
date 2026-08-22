/**
 * 色带表 —— 与后端 app/services/raster_preview_service.py 的 _PALETTES 逐色对齐
 * （2026-08-22 从后端 dump，服务端瓦片即按此渲染，colorbar 必须同源）。
 * 未知 palette id 回落 viridis（与后端 resolve_palette_id 行为一致）。
 */

var PALETTES = {
  'thermal-orange': ['#0b1a6e', '#1b3cff', '#2a5fff', '#2f8cff', '#36c5ff', '#4ad4d0', '#5ad9c4', '#7ce7b0', '#a8e87a', '#c8e86a', '#ffe066', '#ffd166', '#ff9f4a', '#ff7b54', '#ff4d4d', '#e83070', '#c01888'],
  'precip-cyan': ['#061018', '#0b1c30', '#123048', '#16324f', '#1a4a7a', '#1c6dd0', '#1ea0ef', '#1ec8ff', '#48e0ff', '#70f0ff', '#9af8f0', '#b7fff5', '#d8fffb', '#e8ffff', '#ffffff'],
  'wind-blue': ['#6271b8', '#3d6ea3', '#4a94aa', '#4a9294', '#4d8e7c', '#6b9148', '#a89438', '#d07a3a', '#c94e4e', '#a83d7a', '#7a3d9e', '#5c4d6e'],
  'magenta-yellow': ['#1a102a', '#5b1f7a', '#b832e0', '#ff5e9a', '#ffb347', '#fff2a6'],
  viridis: ['#440154', '#414487', '#2a788e', '#22a884', '#7ad151', '#fde725'],
  cividis: ['#00204d', '#285677', '#66837a', '#aaa666', '#e0c95a', '#fde737'],
  spectral: ['#9e0142', '#d53e4f', '#f46d43', '#fdae61', '#fee08b', '#e6f598', '#abdda4', '#66c2a5', '#3288bd'],
  blues: ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594'],
  reds: ['#fff5f0', '#fee0d2', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d'],
  greens: ['#0d2818', '#1a4d2e', '#2d6a4f', '#40916c', '#52b788', '#74c69d', '#95d5b2', '#b7e4c7'],
  'yellow-red': ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#fc4e2a', '#e31a1c', '#b10026'],
  'blue-green': ['#08306b', '#2171b5', '#6baed6', '#66c2a4', '#41ab5d', '#238b45'],
  'red-blue': ['#b2182b', '#ef8a62', '#fddbc7', '#f7f7f7', '#d1e5f0', '#67a9cf', '#2166ac'],
  'purple-orange': ['#2d1b3d', '#542466', '#8c2d80', '#c63e6c', '#f08050', '#ffb347', '#ffe066'],
  'dark-rainbow': ['#1a0033', '#003380', '#0066cc', '#00cc66', '#cccc00', '#cc6600', '#cc0000'],
  ylgnbu: ['#ffffd9', '#c7e9b4', '#7fcdbb', '#41b6c4', '#1d91c0', '#081d58'],
  plasma: ['#0d0887', '#6a00a8', '#b12a90', '#e16462', '#fca636', '#f0f921'],
  hot: ['#000000', '#8b0000', '#ff0000', '#ffff00', '#ffffff'],
  terrain: ['#333399', '#00aa88', '#88cc44', '#ddcc66', '#c4a35a', '#ffffff'],
  tab10: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'],
  ylgn: ['#ffffe5', '#f7fcb9', '#d9f0a3', '#addd8e', '#78c679', '#238443'],
  ylorrd: ['#ffffcc', '#ffeda0', '#fed976', '#feb24c', '#fd8d3c', '#f03b20', '#bd0026'],
  brg: ['#0000ff', '#ff00ff', '#ff0000', '#ffff00', '#00ff00'],
  rdylgn_r: ['#006837', '#31a354', '#78c679', '#c2e699', '#ffffcc', '#fdae61', '#f46d43', '#a50026']
};

// 后端/历史别名 → 规范 id（与后端 resolve_palette_id 的别名对齐）
var ALIASES = {
  'blue-cyan': 'wind-blue'
};

/** 分类色（离散图例用，如土地覆盖） */
var DISCRETE_PALETTES = ['tab10'];

function resolve(paletteId) {
  if (!paletteId) {
    return PALETTES.viridis;
  }
  var key = String(paletteId).toLowerCase();
  if (ALIASES[key]) {
    key = ALIASES[key];
  }
  if (PALETTES[key]) {
    return PALETTES[key];
  }
  // igbp / igbp-landcover-ramp 等未定义色带：后端渲染回落 viridis，前端保持一致
  return PALETTES.viridis;
}

function isDiscrete(paletteId) {
  return DISCRETE_PALETTES.indexOf(String(paletteId || '').toLowerCase()) >= 0;
}

/** colorbar 渐变 CSS（线性均分 stops） */
function gradientCss(paletteId) {
  var stops = resolve(paletteId);
  var parts = [];
  for (var i = 0; i < stops.length; i++) {
    parts.push(stops[i] + ' ' + Math.round((i / (stops.length - 1)) * 100) + '%');
  }
  return 'linear-gradient(to right, ' + parts.join(', ') + ')';
}

/** 生成 [vmin, vmax] 间的 n 个刻度值（含两端） */
function tickValues(vmin, vmax, n) {
  n = n || 5;
  var out = [];
  for (var i = 0; i < n; i++) {
    out.push(vmin + ((vmax - vmin) * i) / (n - 1));
  }
  return out;
}

/** 刻度值格式化 */
function formatValue(v) {
  var a = Math.abs(v);
  if (a >= 10000) {
    return Math.round(v / 1000) + 'k';
  }
  if (a >= 100) {
    return String(Math.round(v));
  }
  if (a >= 10) {
    return String(Math.round(v * 10) / 10);
  }
  if (a >= 1) {
    return String(Math.round(v * 10) / 10);
  }
  return String(Math.round(v * 100) / 100);
}

module.exports = {
  resolve: resolve,
  isDiscrete: isDiscrete,
  gradientCss: gradientCss,
  tickValues: tickValues,
  formatValue: formatValue
};
