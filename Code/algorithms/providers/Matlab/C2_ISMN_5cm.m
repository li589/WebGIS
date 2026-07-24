% 整理ISMN数据（mat格式）
% 匹配SMAP过境时间并提取表层5cm
% 年份：20150401-20211231

% %% 1)提取与SMAP匹配的表层数据 daily
clc; clear; close all;
% 导入数据
load ('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\smap_lat_lon.mat');
path1 = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\MAT\3.6am\';
file1 = dir([path1,'*.mat']);
% landcover
load('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\IGBP_9km_12.mat');
% climate
% 选用0.083degree
load('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\Koppen_present_083.mat');
% path_save
path_sv = 'D:\DDCAfuxian\DDCAdata\DCA_VI_H\Validation\ismn_5cm\';

% % %% 2）site提取2015-2021的观测数值
len = 1;
for i = 1:length(file1)
    load([path1,file1(i).name])
    ismn(:,4) = []; % 删除时间列
    % 剔除数值：年份不在2015-2021，深度>0.05，sm<0.001或>0.6
    date = datenum(ismn(:,1),ismn(:,2),ismn(:,3));
    f1 = find((date < datenum(2015,4,1) | date > datenum(2021,12,31))...
        | ismn(:,8)>=0.051| ismn(:,9)<=0.001 | ismn(:,9)>0.601 );
    if isempty(f1)
        ismn = ismn;
    else
        ismn(f1,:) = [];
    end

    if isempty(ismn)
        continue
    end

    % 按日期排列
    date1 = datetime(2015,4,1):days(1):datetime(2021,12,31);
    date1 = datenum(date1);
    for j = 1:length(ismn(:,1))
        date2 = datenum(ismn(j,1),ismn(j,2),ismn(j,3));
        f2 = find(date1 == date2);
        if isempty(f2)
            continue
        end
        % 行-site;列-date
        site(len,f2) = ismn(j,9);
    end
    % 剔除变化值
    diff1 = site(len,:) - [nan,site(len,1:end-1)]; %前
    diff2 = [site(len,2:end),nan] - site(len,:); %后
    f3 = abs(diff1)>0.1 | abs(diff2)>0.1;
    site(len,f3) = nan;

    % 提取信息lat lon dem
    site_id{len,1} = file1(i).name;
    site_lat(len,1) = ismn(1,4);
    site_lon(len,1) = ismn(1,5);
    site_elev(len,1) = ismn(1,6);
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
save([path_sv,'\ismn_site.mat'],"site_lc","site_kop","site_elev",...
    "site_mesh","site_lon","site_lat","site_id","site","site_lc_smap");

%% 3) 先划分network，再在grid内做site平均
% clc; clear
load('D:\DDCAfuxian\DDCAdata\DCA_VI_H\Validation\ismn_5cm\ismn_site.mat')
load('D:\DDCAfuxian\DDCAdata\SMAP_ancillary\IGBP_9km_12.mat');
for i = 1:length(site_id)
    a = strsplit(string(site_id(i)),'_');
    site_id1(i,1) = a(1);
end
% network
net_id = unique(string(site_id1),"rows","stable");
len = 1;
for i = 1:length(net_id)
    f1 = strcmp(site_id1,net_id(i));
    f1 = find(f1==1);
    % network中计算grid
    mesh_temp1 = site_mesh(f1);
    mesh_temp2 = unique(mesh_temp1,"rows","stable");
    for j = 1:length(mesh_temp2)
        mesh_temp3 = mesh_temp2(j);
        f2 = find(mesh_temp1 == mesh_temp3);
        % data
        grid_temp = site(f1(f2),:);
        grid_temp = mean(grid_temp,1,"omitnan");
        grid(len,:) = grid_temp;
        % info
        grid_mesh(len,1) = mesh_temp3;
        grid_site(len,:) = length(f2);
        grid_vali(len,:) = length(find(~isnan(grid_temp)));
        grid_id(len,:) = site_id(f1(f2(1))); %id仅作为参考
        grid_lat(len,1) = mean(site_lat(f1(f2)));
        grid_lon(len,1) = mean(site_lon(f1(f2)));
        grid_elev(len,1) = mean(site_elev(f1(f2)));
        lc_temp = site_lc(f1(f2));
        grid_lc(len,1) = mode(lc_temp);
        kop_temp = site_kop(f1(f2));
        grid_kop(len,1) = mode(kop_temp);
        len = len+1;
    end
    % network info
    net_site(i,:) = length(f1);
end
grid_lc_smap = IGBP_9km_12(grid_mesh);
% save
save([path_sv,'\ismn_grid.mat'],"grid_lc","grid_kop","grid_elev",...
    "grid_mesh","grid_lon","grid_lat","grid_id","grid","grid_vali","grid_lc_smap");

%% 4）按照network整理
for i = 1:length(grid_id)
    a = strsplit(string(grid_id(i)),'_');
    grid_id1(i,1) = a(1);
end
net_id = unique(string(grid_id1),"rows","stable");
for i = 1:length(net_id)
    f = strcmp(string(grid_id1),net_id(i));
    net_grid(i,:) = length(find(f ==1));
    net_lc{i} = grid_lc(f);
    net_kop{i} = grid_kop(f);
    net(i,:) = mean(grid(f,:),'omitnan');
end
% save
save([path_sv,'\ismn_net.mat'],"net_lc","net_kop","net_id","net");
