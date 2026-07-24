% 对13C1 NDVI 9km数据进行SG滤波和插值，生成每日NDVI
% SG滤波参数： 6，9
% 插值方法：Linear

clc; clear; close all
addpath('D:\DDCAfuxian\DDCAcode\2.Code\Function\')
year = 2014;%%%
start_time = datetime(year,1,1);
end_time = datetime(year,12,31);

%% 1)数据路径
% 更改输入和输出路径！
path1 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\3.NDVI_9km_1014\';
namelist1 =  dir([path1,'*.tif']);
path2 = 'D:\DDCAfuxian\DDCAdata\VNP13C1002\3.NDVI_9km_1014\';
namelist2 =  dir([path2,'*.tif']);
path_sv1 = ('D:\DDCAfuxian\DDCAdata\MYOD13C1\4.Daily_1014\');
path_sv2 = ('D:\DDCAfuxian\DDCAdata\VNP13C1002\4.Daily_1014\');
% 设定输出路径
path = path2;
namelist = namelist2;
path_sv = path_sv2;

%% 2)滤波+插值
% 整理数据
NDVI_all = nan(1624,3856,46);
len = 1;
for i = 1: length(namelist)
    date_temp = datetime(namelist(i).name(1:8),'InputFormat','yyyyMMdd');
    if date_temp < start_time || date_temp> end_time
        continue
    end
    date(len) = datenum(date_temp);
    NDVI = readgeoraster([path,namelist(i).name],"OutputType","double");
    NDVI_all(:,:,len) = NDVI;
    len = len+1;
end

% 滤波+插值
% sg时间序列
date_sg = [start_time:days(8):end_time];
date_sg = datenum(date_sg);
% interp时间序列
date_in = start_time:days(1):end_time;
date_in = datenum(date_in);
% 按像元进行时间序列处理
[m,n,~] = size(NDVI_all);
NDVI_daily = nan(m,n,length(date_in));
for i = 1:m
    tic
    for j = 1:n
        data = reshape(NDVI_all(i,j,:),1,[]);
        if length(find(~isnan(data)))<= 4 %一个月数值8*4,每年5个月
            continue
        end
        data2 = vi_sg_interp(data,date,date_sg,date_in,datenum(start_time),datenum(end_time));
        NDVI_daily(i,j,:) = data2;
    end
    disp(i)
    toc
end

disp(datetime("now"))

%% 输出为每日NDVI文件
z = length(date_in);
for k = 1:z
    NDVI = NDVI_daily(:,:,k);
    % qa控制，去除正常范围外的数值
    NDVI(NDVI>1 | NDVI<0) = nan;
    % save
    nametime = datestr(date_in(k),'yyyymmdd');
    save([path_sv,nametime,'.mat'],'NDVI');
end

disp(datetime("now"))
