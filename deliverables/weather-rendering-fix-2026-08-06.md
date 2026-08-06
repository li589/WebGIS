# 天气图层大范围与缩放渲染修复

## 已完成

修复天气图层在大范围、国际日期变更线附近和缩放结束后出现的半球缺失/粒子流消失问题。

### 关键改动

- `wind-particle-webgl-renderer.ts`
  - 修复世界副本计算：主世界不在屏内时不再强制返回 `[0]`，保留实际可见的相邻世界副本。
  - WebGL 粒子点与风场色场使用同一组 world-wrap offsets。

- `wind-particle-canvas.ts`
  - 平移/缩放交互期间继续保持稳定的 wrap offset。
  - `moveend/zoomend` 后按最新相机重新计算 `lonWrapOffset`，避免粒子被投影到屏外。

- `wind-particle-overlay-controller.ts`
  - 瓦片合并短暂无数据时保留当前粒子层和最后一份 GeoJSON，不再销毁后等待重建。

- `wind-particle-webgl-controller.ts`
  - WebGL 路径同样保留当前粒子层，避免缩放瞬态触发 destroy/recreate 闪空。

- `wind-particle-webgl-texture.test.ts`
  - 新增主世界完全出屏时仍绘制相邻世界副本的回归测试。

- `scalar-field-webgl-shaders.ts`
  - 移除数据 quad 外框的 alpha 羽化；该羽化会使全球数据的主世界与相邻世界副本在国际日期变更线两侧同时透明，形成细小裂缝。
  - 保留基于数据 `mask` 的透明软化，因此真实缺测区域仍会透明。

- `scalar-field-grid.ts` / `scalar-field-webgl-controller.ts`
  - 用 FNV-1a 网格签名替代“所有值求和”的弱 checksum。签名包含网格大小、地理 bounds、mask 与有序数值。
  - 在判重前先比较 bounds；任何 LonFrame / 东西半球 / 覆盖范围改变都会重传纹理并更新 GPU quad，防止旧半球被错误复用。

- `scalar-field-webgl.test.ts`
  - 新增跨日期变更线 scalar grid（170° 到 190°）、同和值不同半球布局签名和 shader 无羽化接缝回归测试。

## 验证

- 第一轮针对性天气测试：52/52 通过
- 第二轮标量场与日期变更线测试：68/68 通过
- 完整前端测试：103 个测试文件，507 个测试全部通过
- `npm run build`：通过
- `git diff --check`：通过

构建仍有既有的第三方 `litegraph.js` direct `eval` 和动态 import 警告，与本次修复无关。

## 注意

本次开始前工作树已经存在大量其他未提交改动。本次只修改了上述天气渲染相关文件，未执行 reset、未覆盖其他改动，也未提交。