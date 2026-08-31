% FY-3F MWRI ORBA 拼接 HDF 后处理
% 输入：FY3F_MWRI_mosaic.py 生成的 FY3F_GBAL_L1_*_ORBA.hdf
% 输出：每日 MAT 文件，变量为 IA、TBv、TBh

clc; clear; close all

%% 路径
path_in  = 'Y:\Chenhaojun\Data\3Ffinal\';
path_out = 'Y:\Chenhaojun\Data\3Fmat\';

if ~exist(path_out, 'dir')
    mkdir(path_out)
end

%% FY-3F ORBA 最终拼接 HDF
namelist = dir(fullfile(path_in, 'FY3F_GBAL_L1_*_ORBA.hdf'));

for i = 1:numel(namelist)
    filename = fullfile(path_in, namelist(i).name);

    % 不依赖文件夹长度，从文件名提取 YYYYMMDD。
    date = regexp(namelist(i).name, '\d{8}', 'match', 'once');
    assert(~isempty(date), '文件名中未找到八位日期：%s', namelist(i).name);

    %% 读取 FY-3F 拼接输出
    TBh_raw = double(h5read(filename, '/EARTH OBSERVE BT 10GHz H'))';
    TBv_raw = double(h5read(filename, '/EARTH OBSERVE BT 10GHz V'))';
    IA_raw  = double(h5read(filename, '/Sensor_Zenith'))';

    % FY-3F 源 HDF 实测属性：
    % TB: FillValue=-32767, Slope=0.009999999776482582,
    %     Intercept=327.67999267578125
    % IA: FillValue=-32768, Slope=0.009999999776482582,
    %     Intercept=0
    % 拼接输出统一 nodata 可能为 -32767；也兼容原始 IA 的 -32768。
    TBh_raw(TBh_raw == -32767) = NaN;
    TBv_raw(TBv_raw == -32767) = NaN;
    IA_raw(IA_raw == -32767 | IA_raw == -32768) = NaN;

    % 与 FY-3D 后处理保持相同的换算写法。
    TBh = TBh_raw .* 0.01 + 327.68;
    TBv = TBv_raw .* 0.01 + 327.68;
    IA  = IA_raw  ./ 100;

    % 保留既有 FY-3D / SMAP 后处理中的 TB 上限筛选；
    % FY-3D 后处理原代码还包含 TB < 0 的筛选。
    TBh(TBh > 330 | TBh < 0) = NaN;
    TBv(TBv > 330 | TBv < 0) = NaN;

    save(fullfile(path_out, [date, '.mat']), 'IA', 'TBv', 'TBh');
    fprintf('%s\n', date)
end
