# 六源数据集在线下载验证报告（2026-08-21）

## 结论：6/6 全部通过 ✅（NSMC 待会话预热后补验）

| 源 | 数据集 | 凭据 | 验证方式 | 耗时 | 结果 |
|---|---|---|---|---|---|
| NOMADS | GFS pgrb2.0p25（TMP 子集） | 无需 | AWS 源单变量子集 GRIB（约 0.5MB） | 2.2s | ✅ |
| CMR | SPL3SMP_E（SMAP L3） | 检索匿名 | granule 检索级验证（单日单条） | 1.3s | ✅ |
| GLDAS | GLDAS_NOAH025_3H v2.1 | Earthdata | CMR 最新日（2026-05-31†）单文件下载 | 16.4s | ✅ |
| SMAP | SPL3SMP_E | Earthdata | 单日 max_files=1 下载 | 34.6s | ✅ |
| CDS | reanalysis-era5-single-levels | CDS token | ERA5 单日极小区域 NetCDF（回退 7 天） | 33.9s | ✅ |
| CDSE | SENTINEL-2 S2MSI2A | Copernicus 账号 | token 交换 + OData 检索 + 单产品下载 | 167.5s | ✅ |
| NSMC | FY3D/FY3F | CMA 门户（3 账号） | — | — | ⏳ 待会话预热 |

† **GLDAS 数据集上游停更于 2026-05-31**（CMR sort_key=-start_date 实证），下载链路正常但最新数据约滞后 3 个月。工作流在线种子选时间范围时须注意此边界。

## 验证工具

`Tools/dataset_download_verify.py`：
```
Env\Python312\python.exe Tools/dataset_download_verify.py --all
Env\Python312\python.exe Tools/dataset_download_verify.py --sources nomads,cmr
```
- 每源独立 try/except 互不阻断；退出码全过 0 / 有失败 1
- 报告：`Tools/reports/dataset_download_verify_<ts>.json`（gitignore 区）
- 下载落盘：`Tools/reports/dataset_verify_tmp/<source>/`（不污染 DATA_ROOT）
- 凭据经后端 `get_portal_credentials_runtime()` 解密读取，密钥值不落日志
- NSMC 占位：检测 `_runtime/cache/nsmc_session.json` 未预热时报 skipped；
  人工跑 `Tools/nsmc_online_probe.py login --code` 预热后可补验

## 期间发现并修复的问题

1. **NOMADS herbie 默认源不可用**（本机网络对 RDA 自签证书链 + RDA 无 .idx）：
   `nomads_download.download_via_herbie` 增加 use='aws' 回退重试；验证脚本
   对齐 6 小时 cycle 并取 ≥18 小时前（AWS Open Data 对最新 cycle 有数小时延迟）。
2. **门户凭据结构适配**：earthdata/esa_copernicus 为扁平 username/password 字段
   （非 accounts 数组）；ecmwf_cds 为扁平 token 字段。
3. **数据发布滞后适配**：GLDAS 查 CMR 最新可用日；CDS 自 7 天前逐日回退；
   CMR/SMAP 回退 8 天。
4. **本机自签证书链**：验证脚本全局禁用 TLS 校验（与 nsmc_online_probe
   verify=False 同款处理；数据完整性靠下载文件非空校验兜底）。

## 环境说明

- 验证时间：2026-08-21 12:06（UTC+8）
- 解释器：Env/Python312/python.exe
- 凭据来源：research_data_settings.sqlite3 门户凭据库（earthdata /
  esa_copernicus / ecmwf_cds 均就绪）
