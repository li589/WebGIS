# Frontend Learning Guide

这个目录现在已经是一个真正可运行的 `Vue 3 + TypeScript + Vite` 前端工程，不再只是空目录骨架。

## 你现在可以怎么理解这个工程

- `src/main.ts`：应用入口，负责挂载 Vue、Pinia 和路由
- `src/App.vue`：最外层壳子，负责放页面路由出口
- `src/app/router.ts`：页面路由配置
- `src/stores/ui.ts`：全局状态示例，这里管理 2D/3D 模式、当前数据图层、当前时间
- `src/views/DashboardView.vue`：页面级组件，负责组织整个 WebGIS 壳子
- `src/components/*.vue`：子组件，分别负责工具栏、图层侧栏、地图区、时间轴、信息面板
- `src/styles/main.css`：全局样式

## 当前学习目标

你不需要一上来就学会所有 Vue 技巧，先把下面这条链路看懂：

1. `main.ts` 如何启动应用
2. `App.vue` 如何渲染页面
3. `DashboardView.vue` 如何组织子组件
4. 子组件如何通过 `props` 接收数据
5. 子组件如何通过 `emit` 把事件传回父组件
6. `Pinia store` 如何管理共享状态

## 当前页面对应的 Vue 知识点

- `ModeToolbar.vue`：按钮点击、事件发送
- `LayerSidebar.vue`：`v-for` 列表渲染、父子通信
- `MapCanvas.vue`：根据状态动态显示不同内容
- `TimelineScrubber.vue`：按钮控制时间步进
- `InfoPanel.vue`：展示父组件汇总后的数据

## 启动方式

在 `Code/frontend` 目录下运行：

```bash
npm install
npm run dev
```

默认开发地址通常是：

```text
http://localhost:5173/
```

生产构建：

```bash
npm run build
```

## 推荐学习顺序

建议你按下面顺序阅读：

1. `src/main.ts`
2. `src/App.vue`
3. `src/views/DashboardView.vue`
4. `src/stores/ui.ts`
5. `src/components/ModeToolbar.vue`
6. `src/components/LayerSidebar.vue`
7. `src/components/MapCanvas.vue`
8. `src/components/TimelineScrubber.vue`
9. `src/components/InfoPanel.vue`

## 下一步你可以自己练习

- 把 `风场`、`降水` 等数据改成你自己的名称
- 给时间轴增加“自动播放”按钮
- 给 2D/3D 模式切换增加不同背景效果
- 把 `MapCanvas.vue` 替换成真实地图容器
- 尝试引入 `MapLibre` 做第一版 2D 地图

## 当前技术说明

- Vue 版本：`3`
- 构建工具：`Vite`
- 语言：`TypeScript`
- 路由：`vue-router`
- 状态管理：`Pinia`

这个版本的目标不是直接做完项目，而是先给你一个适合学习和后续扩展的前端起点。
