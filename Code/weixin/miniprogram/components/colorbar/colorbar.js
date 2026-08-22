/**
 * 顶部自动 colorbar：图层元数据（palette/vmin/vmax/unit）→ 渐变条 + 刻度。
 * 色带与后端 _PALETTES 同源（services/palettes.js），保证与瓦片渲染一致。
 */
var palettes = require('../../services/palettes');

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  properties: {
    visible: {
      type: Boolean,
      value: false
    },
    title: {
      type: String,
      value: ''
    },
    unit: {
      type: String,
      value: ''
    },
    paletteId: {
      type: String,
      value: 'viridis'
    },
    vmin: {
      type: null,
      value: 0
    },
    vmax: {
      type: null,
      value: 1
    }
  },

  data: {
    gradient: '',
    discrete: false,
    swatches: [],
    tickLabels: [],
    classStart: '',
    classEnd: ''
  },

  observers: {
    'paletteId, vmin, vmax': function () {
      var vmin = Number(this.properties.vmin) || 0;
      var vmax = Number(this.properties.vmax);
      if (!isFinite(vmax)) {
        vmax = 1;
      }
      var discrete = palettes.isDiscrete(this.properties.paletteId);
      var data = {
        discrete: discrete,
        gradient: palettes.gradientCss(this.properties.paletteId)
      };
      if (discrete) {
        data.swatches = palettes.resolve(this.properties.paletteId);
        data.classStart = palettes.formatValue(vmin);
        data.classEnd = palettes.formatValue(vmax);
      } else {
        data.tickLabels = palettes
          .tickValues(vmin, vmax, 5)
          .map(palettes.formatValue);
      }
      this.setData(data);
    }
  }
});
