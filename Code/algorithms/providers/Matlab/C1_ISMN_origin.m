% 处理ISMN原始数据
% 计算日平均值和6 AM过境数值

clc; clear; close all
%% 1）save as MAT
path_ISMN = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\STM\';
path_sv = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\MAT\1.Site\';
files = dir(path_ISMN);
files = files(3:end); %剔除异常文件
folders = files([files.isdir]);
for sn = 1:length(folders) % each country
    path = [path_ISMN,folders(sn).name,'\'];
    sites = dir(path);
    sites = sites(3:end); %剔除异常文件
    % sites
    for i=1:length(sites)   % sites
        file = dir([path,sites(i).name,'\*sm_0.*.stm']);
        if isempty(file)
            continue;
        end
        % depth
        for j=1:length(file)
            fid = fopen([path,sites(i).name,'\',file(j).name]);
            % read site information
            data = textscan(fid,'%q %q %q %q %q %q %q %q %q %q %q %q %q %q %q %q %q %q %q');%10 var (different from sites)
            lat  = str2double(data{1,4}(1));
            lon  = str2double(data{1,5}(1));
            elv  = str2double(data{1,6}(1)); %elevation
            d_u  = str2double(data{1,7}(1)); %upper depth
            d_l  = str2double(data{1,8}(1)); %last depth

            % sm
            sm=[];
            f_sm = find(~isnan(str2double(data{1,3})));
            if f_sm(1) == 1
                f_sm(1,:) = [];
            end
            parfor ii = 1:length(f_sm)
                [y,m,d] = ymd(datetime(data{1,1}{f_sm(ii),1},'InputFormat','yyyy/MM/dd'));
                hh = str2double(data{1,2}{f_sm(ii),1}(1:2));
                var  = str2double(data{1,3}(f_sm(ii)));
                q_flag = single(strcmp(data{1,4}(f_sm(ii)),'G')); % quality:G = good = 1
                sm(ii,:) = [y m d hh lat lon elv d_u d_l var q_flag];
            end
            % add information and save as struct
            jj_sm=1;
            if strfind(file(j).name,'_sm_') && ~isempty(data{1,7})
                depth = int8(str2double((data{1,7}(1)))*100);
                if exist('soil','var') && isfield(soil,'m') && isfield(soil.m,['d',num2str(depth,'%03g'),'cm_',num2str(jj_sm,'%02d')])
                    jj_sm = jj_sm+1;
                end
                 soil.m.(['d',num2str(depth,'%03g'),'cm_',num2str(jj_sm,'%02d')]) = ...
                    array2table(sm,'VariableNames',{'YY','MM','DD','HH','lat','lon','elev','depth_u','depth_l','sm','qflag'});
            end
            fclose(fid);
        end

        if isempty(data{1})
            continue;
        end
        % save
        save([path_sv,folders(sn).name,'_',sites(i).name,'.mat'],'soil');
        disp([path_sv,folders(sn).name,'_',sites(i).name, ' is saved'])
        clear soil
    end
    disp(sn)
    disp(datestr(now))
end

%% 2) composite daily SM
clc; clear; close all
path = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\MAT\1.Site\';
path_sv = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\MAT\2.Daily\';
file = dir([path,'*.mat']);

for i = 1:length(file)
    load([path,file(i).name])
    depth = fieldnames(soil.m);
    % 合并所有数据
    ismn = [];
    len_ismn = 1;
    data = [];
    for j=1:length(depth)
        temp = table2array(soil.m.(depth{j}));
        if isempty(temp)
            continue;
        end
        data = [data;temp];
    end

    % 剔除数据
    data(isnan(data(:,10)) | data(:,11)==0 ,:) = [];
    if isempty(data)
        continue
    end
    % 计算日平均值,每个site里的station做平均
    % 日期
    date = datenum(data(:,1),data(:,2),data(:,3));
    date1 = unique(date);
    for p = 1:length(date1)
        f1 = find(date == date1(p));
        temp = data(f1,:);
        % 深度
        deep = temp(:,9);
        deep1 = unique(deep);
        for k = 1:length(deep1)
            f2 = find(deep == deep1(k));
            sm_temp = mean(temp(f2,:),1);

            len = length(sm_temp(:,1));
            ismn(len_ismn:len_ismn+len-1,:) = sm_temp;
            len_ismn = length(ismn(:,1)) + 1;
        end
    end

    % save
    save([path_sv,file(i).name],'ismn');
    disp([path_sv,file(i).name, ' is saved'])
    disp(i)
    disp(file(i).name)
    disp(datestr(now))
    clear data len_ismn
end

%% 3) Hourly SM
% 部分站点集合了多个传感器数据，需要做平均（经纬度是一样的）
clc; clear; close all
path = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\MAT\1.Site\';
path_sv = 'D:\DDCAfuxian\DDCAdata\SM_insitu\ISMN\ISMN_15_230721\MAT\3.6am\';
file = dir([path,'*.mat']);

for i = 1:length(file)
    load([path,file(i).name])
    depth = fieldnames(soil.m);
    % 合并所有数据
    ismn = [];
    len_ismn = 1;
    data = [];
    for j=1:length(depth)
        temp = table2array(soil.m.(depth{j}));
        if isempty(temp)
            continue;
        end
        data = [data;temp];
    end

    % 剔除数据
    % MAP 过境时间 6AM
    data( isnan(data(:,10)) | data(:,11)==0 | data(:,4)~=6,:) = [];
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
        deep = temp(:,9);
        deep1 = unique(deep);
        for k = 1:length(deep1)
            f2 = find(deep == deep1(k));
            sm_temp = mean(temp(f2,:),1);

            len = length(sm_temp(:,1));
            ismn(len_ismn:len_ismn+len-1,:) = sm_temp;
            len_ismn = length(ismn(:,1)) + 1;
        end
    end

    % save
    save([path_sv,file(i).name],'ismn');
    disp(i)
    disp([file(i).name, ' is saved'])
    disp(datestr(now))
    clear data len_ismn
end
