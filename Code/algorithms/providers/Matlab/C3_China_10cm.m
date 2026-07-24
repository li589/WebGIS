% 整理CASMOS站点10cm土壤水分数据
% 年份：20170101-20180101
% 计算日平均、6am并存为mat格式

%% 1)Site 整合
clc; clear; close all;
% path
path1 = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\txt\soil_moisture_2017\';
namelist1 = dir([path1,'*.txt']);
path2 = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\txt\soil_moisture_2018\';
namelist2 = dir([path2,'*.txt']);
path_sv = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\mat\1.Site\';
% site info
opts = detectImportOptions('D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\txt\Sta_infor_2017.csv');
opts.VariableTypes = {'char','double','double','double','double','double','double','double','double',...
    'char' ,'char' ,'char','char' };
opts.VariableNames =  {'id','lat','lon','elv','num10','num20','num30','num40','num50','type','machine','soil','landcover'};
site_info_17 =readtable('D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\txt\Sta_infor_2017.csv',opts);
site_info_18 = readtable('D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\txt\Sta_infor_2018.csv',opts);
site_info = [site_info_17;site_info_18];
site_id= unique(site_info(:,1),"rows","stable");
for i = 1:height(site_id)
    name = cell2mat(table2array(site_id(i,:)));

    % 构建文件路径
    file2017 = [path1, name, '.txt'];
    file2018 = [path2, name, '.txt'];

    % 检查文件是否存在
    exist2017 = exist(file2017, 'file');
    exist2018 = exist(file2018, 'file');

    % 如果两个年份都不存在则跳过
    if ~exist2017 && ~exist2018
        warning('站点 %s 的TXT文件不存在，跳过处理', name);
        continue;
    end

    % 根据实际存在的文件读取数据
    try
        if exist2017 && exist2018
            data1 = readtable(file2017);
            data2 = readtable(file2018);
            data = [data1; data2];
        elseif exist2017
            data = readtable(file2017);
        else
            data = readtable(file2018);
        end

        % 后续处理保持不变
        data = table2array(data);
        % 剔除缺失值
        data(data(:,6) == 9999,6) = nan;
        % 转换单位
        data(:,6) = data(:,6) * 0.01;
        % 对应站点信息
        [~,f]= ismember(site_info(:,1),site_id(i,:));
        f = find(f ==1);
        % 整合sm
        data(:,7) = table2array(site_info(f(1),"lat"));
        data(:,8) = table2array(site_info(f(1),"lon"));
        data(:,9) =  table2array(site_info(f(1),"elv"));
        sm = data;
        % save
        save([path_sv,name,'.mat'],'sm');

        disp(i)
    catch ME
        warning('处理站点 %s 时出错: %s', name, ME.message);
    end
end
%% 2) composite daily SM
clc; clear; close all
path = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\mat\1.Site\';
path_sv = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\mat\2.Daily\';
file = dir([path,'*.mat']);


for i = 1:length(file)
    load([path,file(i).name]);
    data = sm;
    data( isnan(data(:,6)),:) = [];
    if isempty(data)
        continue
    end

    china_10cm = [];
    len = 1;

    % 计算日平均值
    date = datenum(data(:,1),data(:,2),data(:,3));
    date1 = unique(date);
    for p = 1:length(date1)
        f1 = find(date == date1(p));
        temp = data(f1,:);
        % 深度
        deep = temp(:,5);
        deep1 = unique(deep);
        for k = 1:length(deep1)
            f2 = find(deep == deep1(k));
            sm_temp = mean(temp(f2,:),1);
            len1 = length(sm_temp(:,1));
            china_10cm(len:len+len1-1,:) = sm_temp;
            len = length(china_10cm(:,1)) + 1;
        end
    end
    china_10cm(china_10cm(:,1)==0,:) = [];
    china_10cm(:,4) = [];
    % save
    save([path_sv,file(i).name],'china_10cm');
    disp(i)
    clear china_10cm
end

%% 3) Hourly SM
clc; clear; close all
path = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\mat\1.Site\';
path_sv = 'D:\DDCAfuxian\DDCAdata\SM_insitu\CASMOS\mat\3.6am\';
file = dir([path,'*.mat']);

for i = 1:length(file)
    load([path,file(i).name]);
    data = sm;
    china_10cm = [];
    len = 1;

    % 剔除数据
    % 过境时间 6AM
    data( isnan(data(:,6)) | data(:,4)~=6,:) = [];
    if isempty(data)
        continue
    end

    % 日期
    date = datenum(data(:,1),data(:,2),data(:,3));
    date1 = unique(date);
    for p = 1:length(date1)
        f1 = find(date == date1(p));
        temp = data(f1,:);
        % 深度
        deep = temp(:,5);
        deep1 = unique(deep);
        for k = 1:length(deep1)
            f2 = find(deep == deep1(k));
            sm_temp = mean(temp(f2,:),1);
            len1 = length(sm_temp(:,1));
            china_10cm(len:len+len1-1,:) = sm_temp;
            len = length(china_10cm(:,1)) + 1;
        end
    end
    china_10cm(china_10cm(:,1)==0,:) = [];
    % save
    save([path_sv,file(i).name],'china_10cm');
    disp(i)
    clear china_10cm
end
