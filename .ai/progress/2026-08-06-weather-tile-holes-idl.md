# 天气瓦片缩放空洞 / 日界线风场 / 并发提升（2026-08-06）



## 现象



1. 缩放后偶发：**中间主区域无数据、四周有数据**（甜甜圈空洞）。

2. 国际日期变更线附近偶发：**仅线旁窄条有风场，其余视口空白**。

3. 需要适度提高并行以改善响应。



## 根因



| 问题 | 根因 |

|------|------|

| 中心空洞 | 视口瓦片按扫描序入队 + 并发有限 → 边缘先完成；merge 用边缘本级裁掉父级 underlay 后中心既无本级也无垫底；稀缺帧还可能覆盖 `lastMerged` |

| 日界线风场 | WebGL 默认路径：`drawWindField` 有 `computeWorldWrapOffsets`，`uploadParticlePointBuffer` / `drawParticles` 未做世界副本 |

| 响应 | FE/BE/Open-Meteo pool 并发 cap 同为 4，偏保守 |



## 修复



- `sortTilesCenterFirst`：视口瓦片按距中心排序入队（日界线 x 环形距离）。

- `getMergedGeojsonForViewport`：覆盖未齐时用上一帧垫底；稀缺加载中不更新 `lastMerged` 锚点。

- 换 tile z（放大/缩小）均短时拉满并发 boost。

- WebGL 粒子投影按与色场相同的 wrap offsets 复制 NDC 点。

- 并发 cap **4 → 6**（`weather-tile-concurrency` / `tile_service` / `redis_client` Open-Meteo pool）。



## 验证



- `cd Code/frontend && npm run test -- weather-tile-api.tiles-in-bounds weather-tile-manager weather-tile-concurrency wind-particle-webgl`

- `cd Code/frontend && npm run build`

- `Env/Python312/python.exe -m pytest Test/backend/test_weather_tile_service.py -q`

- `launch.py restart backend`（或整栈 restart）后目视：缩放中心、日界线附近风场



## 追加（同日）：大范围亚太仍只显示美洲



**根因（大范围-only）**：部分瓦片合并后 `buildWindGridFromGeoJSON` 盲用 `unwrapLonsToMinimalSpan`；旧美洲缓存经 `tileBoundsOverlapViewport` 的 +360 别名误入 nearby underlay。



**修复**：

1. 建格传入视口 `LonFrame`，帧外点丢弃（风/标量）

2. setViewport 按 desiredKeys 驱逐缓存

3. 半开 overlap；宽跨度 lastMerged 需 ≥0.85 且中心瓦已缓存；中心跳出旧弧清空锚点

4. child prefetch / canvas 宽跨度用 `center.lng`



**验证**：`npm run test -- wind-grid-frame weather-tile-utils map-viewport-sync`



## 追加（同日）：IDL 小片空白 + 流量场半屏不稳定



**现象（与「只亮日界线」相反）**：

1. 大范围缩放时，日界线附近偶发**小片不显示**。

2. 多次缩放后流量场偶发**半屏有线、另一半空白或零星几条**。



**根因**：

| 问题 | 根因 |

|------|------|

| IDL 小片空白 | 按 `desiredKeys` 驱逐缓存误删多 z underlay；`isLonInFrame` / 无 pad 的 LonFrame 过严丢掉日界线附近格点 |

| 流量场半屏 | `resolveStreamlineSeedBounds` 用 min/max 压短跨 IDL 弧；同 checksum early-return + moveend 仅大 zoom 差才重撒 |



**修复**：

1. 驱逐改为仅删与当前视口不相交的瓦片（保留叠瓦任意 z）

2. LonFrame ±3° pad；`isLonInFrame` margin 2.5° + ±360 别名

3. 宽跨度 lastMerged 门槛放宽（~0.65 / 中心或 0.85；允许 parentMatched）

4. 种子框保持连续长弧；`moveend`/`zoomend` 与同 checksum 更新一律重撒



**验证**：`npm run test -- wind-grid-frame weather-tile-utils map-viewport-sync wind-streamline weather-tile-manager`（48 passed）+ `npm run build`

## 追加（同日）：日界线只亮大半半球（网格+粒子）

**现象**：国际日期变更线附近网格色底与粒子流只显示一个半球，选哪侧取决于视口哪边面积更大。

**根因**：`renderWorldCopies` 下 `map.getBounds()` 常只覆盖面积较大的一侧；另一侧以世界副本可见却不进 bbox → 瓦片/LonFrame/`isLonInFrame` 只建大半边网格。世界 wrap 绘制无法补出缺失数据。

**修复**：
1. `estimateLngBoundsFromCenter`（center ± worldSize 半屏）+ `preferVisibleLngBounds`：视觉跨 IDL 或 getBounds 明显偏窄时升级 bbox
2. `buildMapViewportSnapshot` / `tilesInViewport` 接入上述校正
3. 粒子/Canvas 在 geojson 未变时仍刷新 LonFrame；`mergeRoamBounds` 保持长弧；GLSL `windTexUv` 与 TS 中心解包对齐

**验证**：`npm run test -- map-viewport-sync wind-grid-frame wind-streamline weather-tile-api`

## 追加（同日）：近全球半屏 + 日界线阴影细带

**现象**：全球/几乎全球视野仍半屏；网格模式日界线有阴影细带，左右只亮一侧。

**根因**：
1. `getBounds` 近全球时常为 `-170..170`（中心在弧内不触发「缝内扩世界」）→ LonFrame/瓦片留 IDL 窄缝
2. 跨 ±180 的格元 Polygon 被 MapLibre fill 画成绕地球长路径 → 细阴影带

**修复**：跨度≥300° 强制世界范围；`splitAntimeridianCellBounds` 拆格元；半屏估弧阈值 halfSpan≥150°→世界。

**验证**：`npm run test -- map-viewport-sync weather-grid-lattice`

## 追加（同日）：审查 P0/P1 落地

**修复**：
1. `resolveVisibleLngBounds` / `resolveVisibleViewportBBox` 为可见经度弧真源；snapshot、tilesInViewport、粒子 roam、流线撒种统一接入
2. 标量 WebGL LonFrame 传 `map.getCenter().lng`
3. 解包格元移位、`boundsFromCenter` 长路径、`windGridShouldWrapLon`（span>180 或 east>180）、wind checksum 含几何、`isLonInFrame` margin=3、建格 debugLog 受 perf 开关

**验证**：`npm run test -- map-viewport-sync weather-grid-lattice wind-grid-frame wind-streamline wind-particle-canvas weather-tile-api scalar-field-webgl wind-particle-webgl`



## ׷�ӣ�2026-08-14�����ս��ߡ�ֻ��һ��ߡ��ع�

**����**�����������ڱ����ƽ��/����ʱ��������Ƭ/ɫ��ֻ��ʾ�ߵ�һ�ࡣ

**����**��
1. `renderWorldCopies` �� `getBounds` ��ֻ������ϴ��һ�ࣻ�� `transform.worldSize` ��֡δ���������Ĺ����������� �� ֻ�������Ƭ
2. `lngLatToTile` δ wrap δ��һ������ʱ��x ��ǯ�� `n-1`������ƫһ��

**�޸�**��
1. `estimateWorldSizePxFromZoom` ��Ϊ worldSize ���ˣ�`expandLngBoundsIfNearAntimeridian` �� `|center|��150��` ����δ����ʱǿ�ƿ� ��180 ������
2. `lngLatToTile` ���۽� `[-180,180]`��`pointInTileHalfOpen` �� `west<-180` չ����ͬ�����

**��֤**��`npm run test -- map-viewport-sync weather-grid-lattice weather-tile-api.tiles-in-bounds` + `npm run build` + `launch.py restart`
