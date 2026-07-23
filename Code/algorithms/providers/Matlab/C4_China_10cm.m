% 整理China 10cm数据匹配SMAP过境时间
% 年份：20170101-20180101

%% 1)提取与SMAP匹配的表层数据 6am
clc; clear; close all;
% 导入数据
load ('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\smap_lat_lon.mat');
path1 = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\mat\3.6am\';
file1 = dir([path1,'*.mat']);
% landcover
load('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\IGBP_9km_12.mat');
% climate
% 选用0.083degree
load('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\Koppen_present_083.mat');
% sv
path_sv = 'D:\DDCAfuxian\DDCAdata\DCA_VI_H\Validation\china_10cm';

%% 2）site提取2017-2021的观测数值
len = 1;
for i = 1:length(file1)
    load([path1,file1(i).name])
    sm = china_10cm;
    sm(:,4) = []; % 删除时间列-分钟
    % 剔除数值：年份不在2017-2018，深度>10，sm<0.001或>0.6
    date = datenum(sm(:,1),sm(:,2),sm(:,3));
    f1 = find((date < datenum(2017,1,1) | date > datenum(2018,12,31))...
        | sm(:,4)>=11| sm(:,5)<=0.001 | sm(:,5)>0.601 );
    if isempty(f1)
        sm = sm;
    else
        sm(f1,:) = [];
    end
    if isempty(sm)
        continue
    end

    % 按日期排列
    date1 = datetime(2017,1,1):days(1):datetime(2018,12,31);
    date1 = datenum(date1);
    for j = 1:length(sm(:,1))
        date2 = datenum(sm(j,1),sm(j,2),sm(j,3));
        f2 = find(date1 == date2);
        if isempty(f2)
            continue
        end
        % 行-site;列-date
        site(len,f2) = sm(j,5);
    end
    % 剔除变化值
%     diff1 = site(len,:) - [nan,site(len,1:end-1)]; %前
%     diff2 = [site(len,2:end),nan] - site(len,:); %后
%     f3 = abs(diff1)>0.1 | abs(diff2)>0.1;
%     site(len,f3) = nan;

    % 提取信息lat lon dem
    site_id{len,1} = file1(len).name;
    site_lat(len,1) = sm(1,6);
    site_lon(len,1) = sm(1,7);
    site_elev(len,1) = sm(1,8);
    site_vali(len,1) = length(find(~isnan(site(len,:))& site(len,:)~=0));
    len = len+1;
    disp(i)
end
site(site == 0) = nan;

% site对应网格
% lat lon
gsize = 0.05;
X = 90-0.5*gsize:-gsize:-90+0.5*gsize;
Y = -180+0.5*gsize:gsize:180-0.5*gsize;
[lon_05,lat_05] = meshgrid(Y,X);
% mesh
for i = 1:height(site_id)
    lat_temp = site_lat(i);
    lon_temp = site_lon(i);
    % smap
    dif = (lat_smap-lat_temp).^2 + (lon_smap-lon_temp).^2;
    f = find(dif == min(dif(:)));
    site_mesh(i,1) = f(1);
    % lc
    dif1 = (lat_05-lat_temp).^2 + (lon_05-lon_temp).^2;
    f1 = find(dif1 == min(dif1(:)));
    site_mesh1(i,1) = f1(1);
    % climate
    dif2 = (lat_kop-lat_temp).^2 + (lon_kop-lon_temp).^2;
    f2 = find(dif2 == min(dif2(:)));
    site_mesh2(i,1) = f2(1);
    disp(i)
end

% site地类、气候区
site_lc = lc_igbp(site_mesh1);
site_lc_smap = IGBP_9km_12(site_mesh);
site_kop = Koppen(site_mesh2);

% save
save([path_sv,'\china_site.mat'],"site_lc","site_kop","site_elev",...
    "site_mesh","site_lon","site_lat","site_id","site","site_lc_smap");


% % 3) grid内做site平均
% grid_mesh = unique(site_mesh,"rows","stable");
% len = 1;
% for i = 1:length(grid_mesh)
%     mesh_temp = grid_mesh(i);
%     f = find(site_mesh == mesh_temp);
%     grid_temp = site(f,:);
%     grid_temp = mean(grid_temp,1,"omitnan");
%     grid_num(len,:) = length(f);
%     grid_vali(len,:) = length(find(~isnan(grid_temp)));
%     grid(len,:) = grid_temp;
%     grid_id{len,1} = site_id{f}; % 有可能2个network在同一grid，id仅作为参考
%     grid_lat(len,1) = mean(site_lat(f),"omitnan");
%     grid_lon(len,1) = mean(site_lon(f),"omitnan");
%     grid_elev(len,1) = mean(site_elev(f),"omitnan");
%     len = len+1;
%     disp(i)
% end
%
% % grid地类、气候区
% grid_lc_smap = lc_smap(grid_mesh);
% grid_kop = Koppen(grid_mesh);
%
% % 根据地类剔除
% f = find(grid_lc_smap == 0| grid_lc_smap == 11 | grid_lc_smap==13 | grid_lc_smap >=15);
% grid_mesh(f,:) = [];
% grid(f,:) = [];
% grid_num(f,:) = [];
% grid_id(f,:) = [];
% grid_lat(f,:) = [];
% grid_lon(f,:) = [];
% grid_elev(f,:) = [];
% grid_lc_smap(f,:) = [];
% grid_kop(f,:) = [];
% grid_vali(f,:) = [];
%
% % save
% save([path_sv,'china_grid.mat'],"grid_lc_smap","grid_kop","grid_elev",...
%     "grid_mesh","grid_lon","grid_lat","grid_id","grid","grid_vali");
