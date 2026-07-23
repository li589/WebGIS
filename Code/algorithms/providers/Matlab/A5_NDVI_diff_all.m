% 整合每年NDVIdiff数值为多年平均值
clc; clear; close all

path = 'D:\FYdata\VNP13C1002\5.MM\daily\NDVI\1314\';
namelist = dir([path,'*s_*.mat']);

% 检查源数据是否存在
if isempty(namelist)
    error('未找到任何年度数据文件: %s', path);
end

for i = 1:length(namelist)
    fprintf('正在处理: %s (%d/%d)\n', namelist(i).name, i, length(namelist));
    load([path, namelist(i).name]);
    NDVI_mean(:,:,i) = NDVI_v_mean;
    NDVI_max(:,:,i) = NDVI_v_max;
    NDVI_min(:,:,i) = NDVI_v_min;
    NDVI_range(:,:,i) = NDVI_v_range;
    NDVI_diff_mean(:,:,i) = NDVI_v_diff_mean;
    NDVI_diff_std(:,:,i) = NDVI_v_diff_std;
    NDVI_vali(:,:,i) = NDVI_v_vali;
    NDVI_od(:,:,i) = NDVI_v_od;
end

% 计算多年综合指标
NDVI_v_mean = mean(NDVI_mean, 3, "omitnan");
NDVI_v_max = max(NDVI_max, [], 3, "omitnan");
NDVI_v_min = min(NDVI_min, [], 3, "omitnan");
NDVI_v_range = mean(NDVI_range, 3, "omitnan");
NDVI_v_od = sqrt(sum(NDVI_od .^2, 3, "omitnan"));
NDVI_v_od(NDVI_v_od == 0) = nan;
NDVI_v_diff_mean = mean(NDVI_diff_mean, 3, "omitnan");
NDVI_v_diff_std = sqrt(mean(NDVI_diff_std .^2, 3, "omitnan"));
NDVI_v_vali = sum(NDVI_vali, 3, "omitnan");

% 设置保存路径并创建文件夹
save_path = 'D:\FYdata\VNP13C1002\5.MM\daily\NDVI\1314\';
if ~exist(save_path, 'dir')
    fprintf('创建文件夹: %s\n', save_path);
    mkdir(save_path);
end

% 保存结果
save_file = fullfile(save_path, 'VI_v_qa.mat');
fprintf('保存结果至: %s\n', save_file);
save(save_file, ...
    'NDVI_v_mean', 'NDVI_v_max', 'NDVI_v_min', 'NDVI_v_range', ...
    'NDVI_v_od', 'NDVI_v_diff_mean', 'NDVI_v_diff_std', 'NDVI_v_vali');

fprintf('处理完成! 共整合 %d 年数据\n', length(namelist));
