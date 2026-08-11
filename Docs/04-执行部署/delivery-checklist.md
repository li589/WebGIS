# 机构交付检查清单（单机构 / 单 API Key）

产品边界保持**单机构、单写密钥、SQLite**；本清单覆盖去硬编码改造后的上线前核对项。

## 必改环境

| 项 | 变量 / 动作 | 说明 |
|----|-------------|------|
| 数据根 | `BACKEND_DATA_ROOT` | **production 未设将拒启**；勿依赖代码内盘符回退。也可经设置 → 数据源写入 `.env` 后「保存并重启后端」 |
| 产物根 | `BACKEND_OUTPUT_ROOT` | 默认可为 `{DATA_ROOT}/ProjectOutput` |
| UI 重启后端 | `BACKEND_UI_RESTART_ENABLED` | 默认仅 `development` 为 true；生产须显式开启才允许 `POST /config/service/restart` |
| Runtime | `BACKEND_RUNTIME_ROOT` 等 | 与 launch `Code/backend/.data` 双轨，见 `launch/constants.py` |
| 鉴权 | `BACKEND_API_KEYS` / 设置页写入 | 生产勿依赖 development 旁路 |
| MinIO | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | **禁止**沿用 compose 默认 `minioadmin` |
| GEE 加密 | `BACKEND_GEE_CREDENTIALS_ENCRYPTION_KEY` | 非 development 必配 |

## 生产禁止开关

| 开关 | 要求 |
|------|------|
| `BACKEND_DEMO_SOURCES_ENABLED` | **禁止**在生产开启（demo:// 抓取） |
| `BACKEND_NODE_STUBS_VISIBLE` | **禁止**在生产对终端用户开启未实现节点 stub |
| `BACKEND_RELOAD=true` | 生产应显式 `false` |
| `BACKEND_TRUST_PROXY` | 仅受信 Nginx gateway 后开启 |

## 可选白标 / 裁剪

| 项 | 变量 |
|----|------|
| 品牌短名/全名 | `VITE_BRAND_SHORT_NAME` / `VITE_BRAND_FULL_NAME`（构建期） |
| 机构标签（默认「课题组」） | `VITE_ORG_LABEL` |
| 设置 Tab 白名单 | `VITE_SETTINGS_TABS=general,api-keys,about,...` |
| 地图默认 | `BACKEND_MAP_DEFAULT_*` / `BACKEND_MAP_AOI_PRESETS` |
| 天气默认点 | `BACKEND_WEATHER_DEFAULT_*` |

## 目录与种子

- 跑 `npm run check:catalog`（FE `LAYER_LIBRARY.catalogId` ⊆ BE seeds）
- 工作流种子路径使用 `{DATA_ROOT}`；勿再写死盘符
- `source_uri_map`：从 `source_uri_map.example.json` 复制后替换为本机构 URI（示例含实验室 I: 路径）

## 验证

```text
Env\Python312\python.exe -m pytest Test/backend/test_data_root_policy.py Test/backend/test_data_source_paths.py Test/backend/test_catalog_placeholder_filter.py -q
cd Code/frontend && npm run check:catalog && npm run test -- map-defaults restore-workflow-bridge
```

改数据根后：`Env\Python312\python.exe launch.py restart backend`，再 `GET /layers` 确认 `run_readiness`。