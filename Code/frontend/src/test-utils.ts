// 测试支撑垫片（发布就绪 P0-11）。仅被 Test/frontend 的组件渲染测试经 `@/test-utils` 引用。
//
// 为什么需要它：Test/frontend 位于 vite root（Code/frontend）之外。测试文件里直接写
// `import ... from 'pinia' / '@vue/test-utils'` 时，vitest 将 node_modules 依赖外部化并用
// Node 解析，从 root 外的测试文件向上找不到 Code/frontend/node_modules。而本文件位于 root 之内，
// 它对 pinia / @vue/test-utils 的解析会从 Code/frontend 向上命中 node_modules，与现有 446 个
// 纯逻辑测试（经 @/ 进入 src 后解析依赖）是同一机制。生产构建中本文件因未被引用会被 tree-shake。
export { mount, shallowMount } from '@vue/test-utils'
export { createPinia, setActivePinia, createTestingPinia } from 'pinia'
