/**
 * 默认四组的稳定 overlay 编号（纯数据，无任何 store 依赖）。
 *
 * 单独拆出是为了让 `active-layers.ts` 的 removeLayer 也能引用「是否默认图层」判定，
 * 而不会与 `default-layers.ts`（它反过来依赖 selectors → active-layers）形成循环 import。
 *
 * 编号规则：`'imported-' + sha1('<catalogId>|<变量>|<变量>')[:12]`，与后端
 * `stable_imported_layer_id` 及 `Data\ProjectOutput\imports` 目录一一对应。
 * 增删默认图层时，本名单须与 `default-layers.ts::DEFAULT_LAYERS` 的成员保持同步。
 */
export const DEFAULT_LAYER_OVERLAY_IDS: readonly string[] = [
  // 风云 平均（method-fy-omega-doy-avg）
  'imported-55359b8ecd3d', // SM
  'imported-a94205dad5f9', // VOD
  'imported-72aa577da95e', // OMEGA
  // 风云 动态（method-fy-omega-doy-dynamic）
  'imported-fa303afda71e', // SM
  'imported-731b37b59c97', // VOD
  'imported-c6c55b8a9f4e', // OMEGA
  // SMAP 平均（method-smap-season-mean，整段季均）
  'imported-38993117b963', // SM
  'imported-bce85323670f', // VOD
  'imported-49101c3674f8', // OMEGA
  // SMAP 动态（method-smap-omega-doy-dynamic）
  'imported-a8940443fd6d', // SM
  'imported-5427e1020d63', // VOD
  'imported-94501b455dcd', // OMEGA
]

/**
 * 某 overlay 编号是否属于「默认四组」常驻图层（12 个成员）。
 *
 * 默认图层是任何账号/任何电脑打开都要自动加载的底子，「移除」对它只应是
 * **会话内临时视图操作**——刷新必须恢复完整 4 组。所以凡命中这份名单的 overlay，
 * 移除时一律 `dismiss: false`（不写移除名单、不动快照、不跨设备同步），
 * 由 `ensureDefaultLayers` 在下次打开时按稳定编号重新挂回。
 */
export function isDefaultLayerOverlayId(overlayLayerId: string | null | undefined): boolean {
  const id = String(overlayLayerId || '').trim()
  if (!id) return false
  return DEFAULT_LAYER_OVERLAY_IDS.includes(id)
}
