% 计算NDVI dyn 和 clim的差异
clc;clear;close all

%% 设定参数
year = 2014;%年份
date_start = datetime(year,1,1);
date_end = datetime(year,12,31);

%% path
% NDVI_clim
path1 = 'D:\DDCAfuxian\DDCAdata\SMAP_ancillary\NDVI_clim\';
namelist1 = dir([path1,'*.mat']);
% NDVI_dyn VIIRS
path2 = 'D:\DDCAfuxian\DDCAdata\VNP13C1002\4.Daily_1014\';
namelist2 = dir([path2,'*.mat']);
% % NDVI_dyn MODIS
% path3 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\4.Daily\';
% namelist3 = dir([path3,'*.mat']);

%% match
% VIIRS
for i = 1:length(namelist2)
    date_v(i) = datetime(namelist2(i).name(1:8),'InputFormat','yyyyMMdd');
end
f1  = find(date_start<= date_v & date_v<= date_end);

% % MODIS
% for i = 1:length(namelist3)
%     date_m(i) = datetime(namelist3(i).name(1:8),'InputFormat','yyyyMMdd');
% end
% f2  = find(date_start<= date_m & date_m<= date_end);

%% max/min/diff
%% clim
% for i = 1: length(namelist1)
%     load([path1,num2str(i),'.mat']);
%     NDVI1(:,:,i) = NDVI_clim;
%     disp(i)
% end
% NDVI_clim_mean = mean(NDVI1,3,"omitnan");
% NDVI_clim_max = max(NDVI1,[],3,"omitnan");
% NDVI_clim_min = min(NDVI1,[],3,"omitnan");
% NDVI_clim_range = NDVI_clim_max - NDVI_clim_min;
% NDVI_clim_season = prctile(NDVI1_temp,95,3) - prctile(NDVI1_temp,5,3);
% save("D:\2023.01.10 DCA_VI_H\5.Fig\1.DATA\VI_clim.mat",'NDVI_clim_mean',...
%     'NDVI_clim_max','NDVI_clim_min','NDVI_clim_range','NDVI_clim_season');

%% viirs
NDVI1 = nan(1624,3856,length(f1));
NDVI2 = nan(1624,3856,length(f1));
for i = 1: length(f1)
    date = date_v(f1(i));
    % clim
    doy = day(date,'dayofyear');
    load([path1,num2str(doy),'.mat']);
    NDVI1(:,:,i) = NDVI_clim;
    % viirs
    load([path2,namelist2(f1(i)).name]);
    NDVI2(:,:,i) = NDVI;
    disp(i)
end
% check valid num
[m,n,~] = size(NDVI2);
NDVI_v_vali = nan(m,n);
NDVI_v_od = nan(m,n);
for i = 1:m
    for j = 1:n
        data1 = NDVI1(i,j,:); data1 = data1(:);f3 = find(~isnan(data1));
        data2 = NDVI2(i,j,:); data2 = data2(:);f4 = find(~isnan(data2));
        if length(f3)<3 || length(f4)<3
            continue
        end
        NDVI_v_vali(i,j) = length(f4);
        NDVI_v_od(i,j) = dtw(data1(f3),data2(f4));
    end
    disp(i)
end
NDVI2_diff = NDVI2 - NDVI1;
% cal
NDVI_v_mean = mean(NDVI2,3,"omitnan");
NDVI_v_max = max(NDVI2,[],3,"omitnan");
NDVI_v_min = min(NDVI2,[],3,"omitnan");
NDVI_v_diff_mean = mean(NDVI2_diff,3,"omitnan");
NDVI_v_diff_std = sqrt(mean(NDVI2_diff .^2,3,"omitnan"));
NDVI_v_range = prctile(NDVI2,95,3) - prctile(NDVI2,5,3);

save(['D:\FYdata\VNP13C1002\5.MM\daily\NDVI\1314\VI_viirs_',num2str(year),'.mat'],...
    'NDVI_v_mean','NDVI_v_max','NDVI_v_min',...
    'NDVI_v_diff_mean','NDVI_v_diff_std',...
    'NDVI_v_range','NDVI_v_od','NDVI_v_vali');

clear NDVI2
% %% modis
% NDVI3 = nan(1624,3856,length(f2));
% for i = 1: length(f2)
%     date = date_v(f2(i));
%     % clim
%     doy = day(date,'dayofyear');
%     load([path1,num2str(doy),'.mat']);
%     % modis
%     load([path3,namelist3(f2(i)).name]);
%     NDVI3(:,:,i) = NDVI;
%     disp(i)
% end
% % check valid num
% [m,n,~] = size(NDVI3);
% NDVI_m_vali = nan(m,n);
% NDVI_m_od = nan(m,n);
% for i = 1:m
%     for j = 1:n
%         data1 = NDVI1(i,j,:); data1 = data1(:);f3 = find(~isnan(data1));
%         data2 = NDVI3(i,j,:); data2 = data2(:);f4 = find(~isnan(data2));
%         if length(f3)<3 || length(f4)<3
%             continue
%         end
%         NDVI_m_vali(i,j) = length(f4);
%         NDVI_m_od(i,j) = dtw(data1(f3),data2(f4));
%     end
%     disp(i)
% end
% NDVI3_diff = NDVI3 - NDVI1;
% % cal
% NDVI_m_mean = mean(NDVI3,3,"omitnan");
% NDVI_m_max = max(NDVI3,[],3,"omitnan");
% NDVI_m_min = min(NDVI3,[],3,"omitnan");
% NDVI_m_diff_mean = mean(NDVI3_diff,3,"omitnan");
% NDVI_m_diff_std = sqrt(mean(NDVI3_diff .^2,3,"omitnan"));
% NDVI_m_range = prctile(NDVI3,95,3) - prctile(NDVI3,5,3);
%
% save(['D:\DDCAfuxian\DDCAdata\MYOD13C1\5.MM\daily\1518\VI_modis_',num2str(year),'.mat'],...
%     'NDVI_m_mean','NDVI_m_max','NDVI_m_min',...
%     'NDVI_m_diff_mean','NDVI_m_diff_std',...
%     'NDVI_m_range','NDVI_m_od','NDVI_m_vali');
