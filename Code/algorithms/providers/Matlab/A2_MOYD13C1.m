% MYD MOD13C1预处理
% 1)QA 控制
% 2)升尺度为9km，spatial average

%% 1)读取MOD13C1,设定坐标并存储为TIFF
clc;clear; close all;
path_gdal = 'C:\OSGeo4W\bin\';

setenv('PATH', [path_gdal ';' getenv('PATH')]);  % 让系统能找到同一套 DLL
setenv('PROJ_LIB','C:\OSGeo4W\share\proj');      % 指定 proj.db 所在
setenv('GDAL_DATA','C:\OSGeo4W\share\gdal');     % 指定 GDAL 数据目录
path = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\HDF_2010_2014\';
path_sv1 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\2.NDVI_0.05_1014\temp\';


% 检查并创建临时文件夹
if ~exist(path_sv1, 'dir')
    mkdir(path_sv1);
    disp(['创建目录: ', path_sv1]);
end

namelist =  dir([path,'*.hdf']);
len = length(namelist);

for i = 1:len
    hdfname = namelist(i).name;
    name = hdfname(10:16);
    % NDVI
    tifname1 = [name,'NDVI.tif'];
    command = [path_gdal,'gdal_translate.exe ','-a_ullr -180 90 180 -90 ',...
        '-a_srs EPSG:4326 ',...
        '-a_nodata -3000 ',...
        'HDF4_EOS:EOS_GRID:"',[path,hdfname],'":MODIS_Grid_16Day_VI_CMG:"CMG 0.05 Deg 16 days NDVI" ',...
        [path_sv1,tifname1]];
    [~,cmdout] = system(command);
    disp(cmdout);
    pause(3);

    % QA
    tifname2 = [name,'QA.tif'];
    command = [path_gdal,'gdal_translate.exe ','-a_ullr -180 90 180 -90 ',...
        '-a_srs EPSG:4326 ',...
        '-a_nodata 5 ',...
        'HDF4_EOS:EOS_GRID:"',[path,hdfname],'":MODIS_Grid_16Day_VI_CMG:"CMG 0.05 Deg 16 days pixel reliability" ',...
        [path_sv1,tifname2]];
    [~,cmdout] = system(command);
    disp(cmdout);
    disp([hdfname,' convert to ',tifname2,' successful!']);
    pause(3);
end

disp(datestr(now))

%% 2) 转换投影
path_sv1 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\2.NDVI_0.05_1014\temp\';
path_sv2 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\2.NDVI_0.05_1014\temp1\';
path_gdal = 'C:\OSGeo4W\bin\';  % 重新定义path_gdal

% 检查并创建投影转换输出文件夹
if ~exist(path_sv2, 'dir')
    mkdir(path_sv2);
    disp(['创建目录: ', path_sv2]);
end

namelist1 =  dir([path_sv1,'*.tif']);
len = length(namelist1);

for i = 1:len
    inputname = namelist1(i).name;
    outputname1 = inputname;
    command = [path_gdal,'gdalwarp.exe ','-overwrite -s_srs EPSG:4326 -t_srs EPSG:6933 -r near -of GTiff ',...
        [path_sv1,inputname],' ',[path_sv2,outputname1]];
    [~,cmdout] = system(command);
    pause(3); disp(i)
end

disp(datestr(now))

%% 3)对NDVI做计算和处理
clc;clear; close all;
path_sv2 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\2.NDVI_0.05_1014\temp1\';
path_sv3 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\2.NDVI_0.05_1014\NDVI\';

% 检查并创建NDVI输出文件夹
if ~exist(path_sv3, 'dir')
    mkdir(path_sv3);
    disp(['创建目录: ', path_sv3]);
end

namelist1 =  dir([path_sv2,'*NDVI.*']);
namelist2 =  dir([path_sv2,'*QA.*']);
len = length(namelist1);

for i = 1:len
 name_ndvi = namelist1(i).name;
    name_qa   = namelist2(i).name;

    % === 加在这里：打印当前"隐式匹配"的一对文件 ===
    disp([name_ndvi, '  <->  ', name_qa])
    year = str2double(name_ndvi(1:4));
    day = str2double(name_ndvi(5:7));
    date = datetime(year,1,day);
    nametime = datestr(date,'yyyymmdd');
    % NDVI
    [NDVI,R] = readgeoraster([path_sv2,namelist1(i).name],"OutputType","double");
    [QA,~] = readgeoraster([path_sv2,namelist2(i).name],"OutputType","double");
    NDVI(NDVI>10000 | NDVI<-2000 | QA~=0) = nan;
    NDVI = NDVI*0.0001;
    % save
    geotiffwrite([path_sv3,nametime,'.tif'],NDVI,R,'CoordRefSysCode',6933);
    disp(i)
end

disp(datestr(now))

%% 4)NDVI重采样到9km
clc; clear; close all
path_gdal = 'C:\OSGeo4W\bin\';   % 先定义，再 setenv
setenv('PATH', [path_gdal ';' getenv('PATH')]);
setenv('PROJ_LIB','C:\OSGeo4W\share\proj');
setenv('GDAL_DATA','C:\OSGeo4W\share\gdal');

path_sv3 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\2.NDVI_0.05_1014\NDVI\';
path_sv4 = 'D:\DDCAfuxian\DDCAdata\MYOD13C1\3.NDVI_9km_1014\';


% 检查并创建重采样输出文件夹
if ~exist(path_sv4, 'dir')
    mkdir(path_sv4);
    disp(['创建目录: ', path_sv4]);
end

namelist1 =  dir([path_sv3,'*.tif']);
len = length(namelist1);

for i = 1:len
    inputname = namelist1(i).name;
    outputname = inputname;
    command = [path_gdal,'gdalwarp.exe ','-overwrite -te -17367530.45 -7314540.83 17367530.45 7314540.83 '...
        '-ts 3856 1624 -r average -of GTiff ',...
        [path_sv3,inputname],' ',[path_sv4,outputname]];
    [~,cmdout] = system(command);
    pause(3); disp(i)
end

disp(datestr(now))
