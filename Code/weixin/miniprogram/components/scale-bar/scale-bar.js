/**
 * 比例尺：输入 metersPerPixel（regionchange scale → mercator.metersPerPixel），
 * 取 1/2/5 × 10^n 的整数距离，目标条宽 ≤ 96px。
 */
var TARGET_PX = 96;

Component({
  options: {
    // 允许父级（map-shell）通过 class 定位组件插槽
    styleIsolation: 'apply-shared'
  },

  properties: {
    metersPerPixel: {
      type: Number,
      value: 0
    }
  },

  data: {
    barWidth: 0,
    halfWidth: 0,
    label: ''
  },

  observers: {
    metersPerPixel: function (mpp) {
      if (!mpp || mpp <= 0) {
        this.setData({ barWidth: 0, halfWidth: 0, label: '' });
        return;
      }
      var raw = mpp * TARGET_PX; // 目标像素宽对应的米数
      var pow = Math.pow(10, Math.floor(Math.log10(raw)));
      var nice = pow;
      var candidates = [1, 2, 5, 10];
      for (var i = 0; i < candidates.length; i++) {
        if (candidates[i] * pow <= raw) {
          nice = candidates[i] * pow;
        }
      }
      var px = nice / mpp;
      var label = nice >= 1000 ? (nice / 1000) + ' km' : nice + ' m';
      this.setData({
        barWidth: Math.round(px),
        halfWidth: Math.round(px / 2),
        label: label
      });
    }
  }
});
