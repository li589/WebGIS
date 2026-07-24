%前一步为FY3B.py
clc;clear;close all

%% 1) importdata
path = ('Y:\Chenhaojun\1012\1012\');
path_sv = ('Y:\Chenhaojun\1012\mat\');
namelist =  dir([path,'*.hdf']); %所有h5文件信息
len = length(namelist); %文件个数

for i = 1:len
    filename = [path,namelist(i).name];
    date = filename(51:58);
    fileinfo = h5info(filename);

    % input
    % TBh
    TBh1 = double(h5read(filename,'/EARTH OBSERVE BT 10GHz H'))';
    TBh = TBh1.*0.01+327.68;
    TBh(TBh > 330 | TBh < 0)= nan;
    % TBv
    TBv1 = double(h5read(filename,'/EARTH OBSERVE BT 10GHz V'))';
    TBv = TBv1.*0.01+327.68;
    TBv(TBv > 330 | TBv < 0)= nan;
    % IA
    IA = double(h5read(filename,'/SensorZenith'))';
    IA = IA/100;

    % save
    name = ['Y:\Chenhaojun\1012\mat\',date,'.mat'];
    save(name,"IA","TBv","TBh");
    disp(date)
end
