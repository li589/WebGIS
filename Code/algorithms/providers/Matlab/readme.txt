这是课题组算法原始代码，仅供参考，禁止修改。

目录内容（fy拼接）：
- B2_FY3D_TB.m / B3_FY3B_TB.m —— FY3D / FY3B MWRI 拼接 HDF 的 MATLAB 后处理（TB→mat）
- B4_FY3F.m —— FY-3F MWRI ORBA 拼接 HDF 后处理（TB FillValue=-32767、IA 兼容 -32767/-32768、TB=raw*0.01+327.68、IA=raw/100、TB>330 或 <0 置 NaN）
- FY3B.py / FY3d.py —— FY3B / FY3D Python 版拼接脚本
- FY3F_MWRI_mosaic.py —— FY-3F MWRI L1 ORBA 拼接（GDAL CLI geoloc→4326→EASE2 6933；
  FY3F TB 为 (scanline,pixel,channel) 3D，GDAL 暴露为转置多波段栅格，需先经 h5py
  抽通道为 2D 临时 HDF5；SDS：//Window_Channel/Calibration/EARTH_OBSERVE_BT 等）

与仓库 Python 实现的对应关系：
- FY3B / FY3D 已合并入算法包（ingest/fy.py 文件发现 + algorithms/fy.py
  FY3B_PROFILE/FY3D_PROFILE 命令链 + utils/fy_executor.py 执行器）。
- FY3F 已于 2026-08-20 接入（本轮）：algorithms/fy.py FY3F_PROFILE（3D TB 抽通道
  EXTRACT_TB_CHANNEL 步骤）、ingest/fy.py ORBA 轨道识别、modules/fy_download.py
  satellite="FY3F"（简写 "3F"）、种子 omega_sf_fenkuai_fy_online FY3F 支路
  （默认 disabled）。原始快照与仓库实现存在 1 字节级差异与空白规范化，语义一致。
