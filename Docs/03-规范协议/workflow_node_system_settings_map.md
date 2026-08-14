# 工作流节点 path 字段 ↔ 系统设置映射

契约真源：`Code/frontend/src/composables/node-form-system-settings-map.ts`

新增下载/预处理节点时，在该文件的 `NODE_FORM_SYSTEM_SETTINGS_MAP` 中登记 `nodeType` 与 `formFields`，并在对应 `*Form.vue` 中通过 `fieldMapForNodeType(nodeType)` 接入 `system-settings-fill`。

| nodeType | 表单字段 | 系统设置键 |
|----------|----------|------------|
| `download/fy_preprocess` | `input_dir`, `output_dir` | `dataRoot`, `outputRoot` |
| `download/gldas_download` | `local_dir` | `dataRoot` |
| `download/nsidc_smap_download` | `local_dir` | `dataRoot` |
| `download/ssh_sync` | `local_path` | `dataRoot` |
