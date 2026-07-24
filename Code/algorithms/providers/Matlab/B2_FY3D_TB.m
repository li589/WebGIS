%前一步为FY3Dfinalfinal
clc;clear;close all

%% 1) importdata
path = ('E:\FY3D_output\que\');
path_sv = ('E:\FY3D_output\que\mat\');
namelist =  dir([path,'*.hdf']); %所有h5文件信息
len = length(namelist); %文件个数

for i = 1:len
    filename = [path,namelist(i).name];
    date = filename(46:53);
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
    IA = double(h5read(filename,'/Sensor_Zenith'))';
    IA = IA/100;

    % save
    name = ['E:\FY3D_output\que\mat\',date,'.mat'];
    save(name,"IA","TBv","TBh");
    disp(date)
end
