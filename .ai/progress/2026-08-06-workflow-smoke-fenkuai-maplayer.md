# Workflow smoke matrix

- Generated: 2026-08-06 21:27 中国标准时间
- API: http://127.0.0.1:8000
- DATA_ROOT: I:\Geograph_DataSet
- Definitions listed: 24

## Matrix

| batch | workflow_id | run_id | status | elapsed_s | blocker / detail |
|-------|-------------|--------|--------|-----------|------------------|
| F | `omega_sf_fenkuai_smap_single` | `run-5ac4e82b6c18` | succeeded | 154.77 |  |

## Notes

- **Map-layer fix verification:** `output_map_layer` now treats non-dict `data` (ArtifactRef / upstream manifest) as `manifest`. Fenkuai light-smoke keeps the canvas `output/map_layer` node. Unit: `test_output_map_layer_accepts_manifest_on_data_port`. Run `run-5ac4e82b6c18` succeeded (~155s), `product_count=5`.

