/**
 * marked-katex-extension 类型垫片（第三方包类型入口缺陷的兜底）。
 *
 * 缘由：该包（v5.1.12）package.json 的 `types` 与 `exports["."].types` 都指向
 * `./src/index.ts`——**源码**而非 .d.ts。TS 因此把第三方源码纳入本项目 program，
 * 本项目开启的 `noUnusedParameters: true` 直接把它内部的 `blockKatex(options, …)`
 * 判为未使用参数，`vue-tsc` 报 TS6133。`skipLibCheck` 只跳过 .d.ts，对 .ts 源码无效；
 * node_modules 中的文件也不应手改（`npm ci` 会覆盖）。
 * （注：单纯写 `declare module '…'` 无效——可解析的真实包优先于环境模块声明。）
 *
 * 做法：按上游 src/index.ts 的**真实导出面**就地声明本模块，并在
 * `tsconfig.app.json` 的 `paths` 中把该包名指向本文件。
 * `paths` 只影响 TS 的类型解析——本项目 Vite 使用显式 `resolve.alias`（未启用
 * vite-tsconfig-paths），故打包解析不受影响。
 *
 * ⚠️ 升级该依赖时须复核上游导出是否变化：
 *   `node_modules/marked-katex-extension/src/index.ts` 的 export 清单。
 * 若上游改为随包发布 .d.ts（types 指向 .d.ts），可直接删除本垫片与 paths 条目。
 */
import type { KatexOptions } from 'katex'
import type { MarkedExtension } from 'marked'

/** 上游 `MarkedKatexOptions`：katex 渲染选项 + nonStandard 宽松 `$…$` 解析开关 */
export interface MarkedKatexOptions extends KatexOptions {
  nonStandard?: boolean
}

export default function markedKatex(options?: MarkedKatexOptions): MarkedExtension
