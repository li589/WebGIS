# GPU 性能检测对话框重写计划

## 问题诊断

当前 `GpuPerfTestDialog.vue` 的三个性能测试存在根本性缺陷，导致测试结果不真实：

| 测试 | 当前实现 | 核心问题 |
|------|---------|---------|
| WebGL 渲染速度 | 3 顶点三角形 + 纯色着色器，`gl.finish()` 循环 1000 次 | GPU 工作量趋近于零，测的是 JS API 调用开销，476190 FPS 无意义 |
| Canvas 2D 填充速率 | 同步循环 10000 次 `fillRect` | 浏览器批量延迟 2D 命令，计时不反映实际栅格化开销 |
| 动画帧率 (RAF FPS) | 循环体仅 `frames++`，无任何绘图 | 测的是 vsync 刷新率（恒定 60Hz），与 GPU 性能无关 |
| GPU 信息详情 | 查询 renderer/vendor/extensions | 无问题，保留不动 |

## 集成约束（不可破坏）

1. **`SystemResourceMetrics.vue`** — 通过 `<GpuPerfTestDialog :open="..." @close="..." />` 集成，props/emits 接口不能变
2. **`usePanelManager.ts`** — 监听 `cgda:perf-test-start` / `cgda:perf-test-end` CustomEvent 暂停风场动画，事件名和时机不能变
3. **不新增文件** — 所有改动在 `GpuPerfTestDialog.vue` 单文件内完成
4. **不新增外部依赖** — 纯原生 WebGL + Canvas 2D API

## 重写后的测试场景

### 测试 1：WebGL 片段着色器压力测试（Mandelbulb 光线追踪）

**目标**：测量 GPU 片段着色器 ALU/三角函数吞吐能力。

- 全屏 quad（2 个三角形），片段着色器对每像素执行 ray marching
- Mandelbulb 分形距离估计器：10 次迭代/步，每次含 `pow`、`acos`、`atan`、`sin`、`cos`
- 光线行进最大 64 步 → 64×10 = 640 次三角迭代/像素
- 画布内部分辨率 512×512 = 262144 像素
- 相机持续轨道运动（`uTime` uniform 驱动），防止驱动缓存优化
- 预计计算量 ~1.68 亿次三角运算/帧，足以让中端 GPU 降至 30-60 FPS

### 测试 2：WebGL 粒子系统（顶点吞吐 + 混合）

**目标**：测量 GPU 顶点处理、光栅化和混合吞吐。

- 20000 个粒子作为 `GL_POINTS` 渲染
- 顶点着色器中做程序化物理动画：轨道运动 + 重力波 + 相位偏移
- 每帧仅更新 `uTime` uniform，所有位置在 GPU 端计算
- 片段着色器渲染软边圆形点精灵，启用 alpha 混合

### 测试 3：Canvas 2D 动画压力测试

**目标**：测量 2D Canvas 栅格化引擎在真实动画场景下的吞吐。

- 1500 个弹跳圆形粒子，每帧更新位置 + 碰撞反弹
- 每个粒子使用 `createRadialGradient` 绘制径向渐变（Canvas 2D 最重的操作之一）
- 半透明背景擦除制造拖尾效果
- RAF 驱动动画循环

### 测试 4：GPU 信息详情（保留不变）

## 统一测量框架

所有动画测试共用 `measureAnimation()` 函数：

```typescript
interface FrameStats {
  fps: number           // 平均 FPS
  frameTimeMs: number   // 平均帧时间 (ms)
  minFps: number        // 最低帧 FPS
  maxFps: number        // 最高帧 FPS
  stability: number     // 稳定性评分 0-100
  totalFrames: number   // 测量期总帧数
}

async function measureAnimation(
  renderFrame: (dt: number) => void,
  warmupMs = 800,    // 预热：让 GPU 时钟稳定、着色器缓存预热
  measureMs = 2200,  // 测量：收集帧时间
): Promise<FrameStats>
```

**测量协议**：
1. 预热阶段（800ms）：运行 RAF 但不记录数据
2. 测量阶段（2200ms）：记录每帧 `performance.now()` 差值
3. 统计：`fps = 1000 / avgFrameTime`，`stability = clamp(100 - CV*200, 0, 100)`（CV = stdDev/mean）

**时长预算**：4 个测试 × ~3s + 间隙 ≈ 10s，在 15s 预算内。

**评分阈值**：

| 测试 | pass | warn | fail |
|------|------|------|------|
| Mandelbulb 着色器 | ≥30 FPS | ≥15 FPS | <15 |
| 粒子系统 | ≥45 FPS | ≥30 FPS | <30 |
| Canvas 2D | ≥45 FPS | ≥30 FPS | <30 |

## UI 改进

| 改进点 | 当前 | 改进后 |
|--------|------|--------|
| 测试可视化 | 无，纯数字 | 嵌入可见 canvas，实时显示渲染画面 |
| 进度反馈 | 仅百分比 | 百分比 + 当前测试名称 + 阶段指示 |
| 结果信息量 | 仅 FPS + 一行 detail | FPS + 帧时间 + min/max FPS + 稳定性评分条 |
| 总体评价 | 无 | 底部综合评分 + 等级标签 |

结果卡片布局：
```
┌─────────────────────────────────────────────────────────┐
│  WebGL 着色器压力测试 (Mandelbulb)           42 FPS      │
│  光线追踪 · 512×512 · 64步/10迭代                        │
│  帧时间 23.8ms · 最低 28 / 最高 60 FPS                  │
│  稳定性 ████████░░ 85%                                   │
└─────────────────────────────────────────────────────────┘
```

## 实现步骤

1. **定义类型与常量**：`FrameStats` 接口、扩展 `TestResult`（增加 `subtitle`、`stabilityScore`）、着色器源码常量、测试参数常量
2. **实现 `measureAnimation()`**：RAF 循环 + 预热 + 帧时间统计
3. **实现 WebGL 工具函数**：`createShader`、`createProgram`、`createFullscreenQuad`、资源清理
4. **重写 `testWebglShaderStress()`**：Mandelbulb 着色器 + 全屏 quad + measureAnimation
5. **重写 `testWebglParticles()`**：20000 粒子 + 物理动画 + 混合 + measureAnimation
6. **重写 `testCanvas2dAnimation()`**：1500 渐变粒子 + measureAnimation
7. **保留 `testGpuInfo()` 不变**
8. **更新 `TESTS` 数组与 `runAllTests()`**：测试函数接收 previewCanvas ref
9. **重写 `<template>`**：新增可见 canvas、当前测试名称、多行结果卡片、总体评价
10. **更新 `<style>`**：结果卡片多行布局、canvas 容器、稳定性进度条、总体评价样式

## 边界处理

- WebGL 上下文：优先 WebGL2 回退 WebGL1，关闭抗锯齿
- 着色器编译错误：检查 COMPILE_STATUS，失败时返回 fail 结果而非异常
- Highp 精度：检查 `getShaderPrecisionFormat`，不支持时回退 mediump
- GPU 资源清理：每个测试结束后 deleteProgram/deleteShader/deleteBuffer
- 可见 canvas 即测量目标：内部分辨率 512×512，CSS 缩放适配对话框宽度
- 后台标签页防护：`document.visibilitychange` 监听，隐藏时提示保持前台

## 验证方法

1. **编译检查**：`cd Code/frontend && npm run build`
2. **Lint 检查**：`cd Code/frontend && npm run lint`
3. **手动验证**（核心）：
   - 打开设置 → 系统资源 → 点击「性能检测」
   - 确认对话框中出现可见 canvas 预览画面
   - 确认 Mandelbulb 测试能看到分形渲染
   - 确认粒子测试能看到粒子飞舞
   - 确认 Canvas 2D 测试能看到彩色粒子弹跳
   - 确认 FPS 数值在合理范围（Mandelbulb 15-120 FPS，而非 476190）
   - 确认帧时间、min/max FPS、稳定性评分均有数值
   - 确认总时长在 10-15 秒内
4. **集成验证**：测试期间地图风场动画暂停，测试结束后恢复
5. **多次运行一致性**：连续运行 2-3 次，结果波动在 ±15% 内
