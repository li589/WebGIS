% 处理SMAPL3元数据产品并存储为mat
% 计算静态参数数值
clc;clear;close all

%% 1) importdata
path = ('Y:\Chenhaojun\smaptb2025\SPL3SMP_E_006-20260204_113111\');
path_sv = ('Y:\Chenhaojun\smaptb2025\2025mat\');
namelist =  dir([path,'*.h5']); %所有h5文件信息
len = length(namelist); %文件个数

for i = 1:len
    filename = [path,namelist(i).name];
    date = filename(71:78);
%     fileinfo = h5info(filename);

    % input
    % TBh
    TBh = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/tb_h_corrected'))';
    TBh(TBh > 330 | TBh == -9999)= nan;
    % TBv
    TBv = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/tb_v_corrected'))';
    TBv(TBv > 330 | TBv == -9999)= nan;
    % surface tempeerature
    Ts = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/surface_temperature'))';
    Ts(Ts < 253.15 | Ts>313.15 | Ts==-9999) = nan;
    % vwc
    vwc = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/vegetation_water_content'))';
    vwc(vwc > 30 | vwc< 0 | vwc==-9999) = nan;
    % IA
    IA = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/boresight_incidence'))';
    IA(IA == -9999)= nan;
    % soil moisture dca
    sm_dca = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/soil_moisture_dca'))';
    sm_dca(sm_dca==-9999) = nan;
    % soil moisture dca
    sm_scav = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/soil_moisture_scav'))';
    sm_scav(sm_scav==-9999) = nan;
    % vod
    vod_dca = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/vegetation_opacity_dca'))';
    vod_dca(vod_dca==-9999) = nan;
    vod_sca = double(h5read(filename,'/Soil_Moisture_Retrieval_Data_AM/vegetation_opacity_scav'))';
    vod_sca(vod_sca ==-9999) = nan;

    % save
    name = ['Y:\Chenhaojun\smaptb2025\2025mat\',date,'.mat'];
    save(name,"vod_dca","vod_sca","sm_dca","sm_scav","IA","vwc","Ts","TBv","TBh");
    disp(date)
end

disp(datetime("now"))

% %% 静态数据albedo bd cf h
% clc
% clear
% % 1) smap文件信息
% path = ('E:\SMAP_L3_P_E_V5\2017\');
% namelist =  dir([path,'*.h5']); %所有h5文件信息
% len = length(namelist); %文件个数
%
% % 2）变量名称
% dataname = 'albedo_dca';
% % albedo_dca
% % roughness_coefficient_dca
% % bulk_density
% % clay_fraction
%
% % 3）选取10数据按像元存储数据
% len = 1;
% data=[];
% for i = 152:181 %6月
%     filename = [path,namelist(i).name];% 获取文件名
%     data(:,:,len) = double(h5read(filename,['/Soil_Moisture_Retrieval_Data_AM/',dataname]))';
%     len = len+1;
% end
%
% % 4）逐像元合成一个数值
% data(data ==-9999)=nan;
% data = mean(data,3,"omitnan");
%
% imagesc(data,"AlphaData",~isnan(data))
% ALBEDO = data;
% save('E:\SMAP_Ancillary\ALBEDO.mat','ALBEDO')
%
% %% B
% clc
% clear
% % 1) smap文件信息
% path = ('E:\SMAP_L3_P_E_V5\MAT\');
% namelist =  dir([path,'*.mat']);
% len = length(namelist);
% load('E:\SMAP_Ancillary\Landcover\IGBP_9km.mat');
%
% % NDVI信息
% path2 = ('E:\SMAP_Ancillary\NDVI\M09_MAT\');
% namelist2 =  dir([path2,'*.mat']);
% len2 = length(namelist2);
% load('D:\DCA_VI_H\5.Fig\1.DATA\VI_clim.mat')
% NDVI_max = NDVI_clim_max; NDVI_min = NDVI_clim_min;
% clear NDVI_clim_*
%
% % 2）选取所有数据按像元存储
% len = 1;
% data= [];
% for i = 1:366
%     name1 = namelist(i).name;
%     load([path,name1])
%
%     date = datetime(name1(1:8),'InputFormat','yyyyMMdd');
%     doy = day(date,'dayofyear');
%     load([path2,num2str(doy),'.mat']);
%
%     B_daily(:,:,len) = (vod_sca).*cosd(IA) ./ vwc; %
%     SF_daily(:,:,len) = sf_lc(vwc,NDVI_clim,NDVI_max,lc_smap);
%     len = len+1;
%     disp(i)
% end
%
% % 3）逐像元合成一个数值
% B = mean(B_daily,3,"omitnan");
% figure(1)
% imagesc(B,"AlphaData",~isnan(B))
% SF = mean(SF_daily,3,"omitnan");
% figure(2)
% imagesc(SF,"AlphaData",~isnan(SF))
%
% % 4)根据LC对B进行填充
% % IGBP 2015
% % B(lc_smap == 0 | lc_smap == 11 | lc_smap == 15 |lc_smap == 16) = 0;
% % SF(lc_smap == 0) = nan;
% % SF(lc_smap == 15| lc_smap==16) = 0;
%
% % 5) LUT中的数值
% % B
% B_smap = nan(1624,3856);
% B_smap(lc_smap == 0 | lc_smap == 11 | lc_smap == 15 |lc_smap == 16) = 0;
% B_smap(lc_smap == 1 | lc_smap == 2 | lc_smap == 13) = 0.1;
% B_smap(lc_smap == 3 | lc_smap == 4) = 0.12;
% B_smap(lc_smap >= 5 & lc_smap <= 9 | lc_smap == 12 |lc_smap == 14) = 0.11;
% B_smap(lc_smap == 10) = 0.13;
% figure(3)
% imagesc(B_smap,"AlphaData",~isnan(B_smap))
% % SF
% SF_smap = nan(1624,3856);
% SF_smap(lc_smap == 1) = 15.96;
% SF_smap(lc_smap == 2) = 15.96;
% SF_smap(lc_smap == 3) = 7.98;
% SF_smap(lc_smap == 4 | lc_smap == 5) = 12.77;
% SF_smap(lc_smap == 6 | lc_smap == 9) = 3;
% SF_smap(lc_smap == 7 | lc_smap == 10) = 1.5;
% SF_smap(lc_smap == 8 | lc_smap == 11) = 4;
% SF_smap(lc_smap == 12) = 3.5;
% SF_smap(lc_smap == 13) = 6.49;
% SF_smap(lc_smap == 14) = 3.25;
% SF_smap(lc_smap == 15 | lc_smap == 16) = 0;
% figure(4)
% imagesc(SF_smap,"AlphaData",~isnan(SF_smap))
%
% % 6）save
% save('E:\SMAP_Ancillary\B.mat','B','B_smap');
% save('E:\SMAP_Ancillary\SF.mat','SF','SF_smap');
