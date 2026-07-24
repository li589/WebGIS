% function data_in = vi_sg_interp(data, date, date_sg, date_in,date_start,date_end)
% % 对NDVI时间序列进行SG滤波+插值
% % data: NDVI原始数据
% % date: NDVI时间序列
% % date_sg: NDVI滤波时间序列（原本时间间隔），datenum格式
% % date_in: NDVI插值时间序列
% % SG滤波参数：阶数6，窗口9
% % 插值方法：linear，不外插
%     % 1）按照8天间隔插值
%     % 13C1从每年1月1开始，按照8天插入
%     f1 = find(~isnan(data));
%     data_in1 = interp1(date(f1),data(f1),date_sg,"linear");
%     % 2）滤波
%     data_sg = sgolayfilt(data_in1,6,9);
%     % 3）插值到每日
%     data_in2 = interp1(date_sg,data_sg,date_in,"linear");
%     % 4）剔除原始数据中间隔32天以上的插值数据
%     f2 = ~isnan(data) & date>=date_start & date<=date_end;
%     date_vali = date(f2);
%     cut = date_vali(1,2:end) - date_vali(1,1:end-1);
%     f3 = find(cut>32); %大于32天间隔的数据
%     date_start = date_vali(f3);
%     date_end = date_vali(f3+1);
%     for i = 1:length(date_start)
%         a = date_start(i);
%         b = date_end(i);
%         data_in2(date_in>a & date_in<b) = nan;
%     end
%     % 4）剔除整个研究期内有效数据小于30个的像元（基于插值后的日序列统计）
%     if sum(~isnan(data_in2)) < 30
%         data_in = nan(size(data_in2));
%     else
%         data_in = data_in2;
%     end
% end


function data_in = vi_sg_interp(data, date, date_sg, date_in,date_start,date_end)
% 对NDVI时间序列进行SG滤波+插值
% data: NDVI原始数据
% date: NDVI时间序列
% date_sg: NDVI滤波时间序列（原本时间间隔），datenum格式
% date_in: NDVI插值时间序列
% SG滤波参数：阶数6，窗口9
% 插值方法：linear，不外插
    % 1）按照8天间隔插值
    % 13C1从每年1月1开始，按照8天插入
    f1 = find(~isnan(data));
    data_in1 = interp1(date(f1),data(f1),date_sg,"linear");
    % 2）滤波
    data_sg = sgolayfilt(data_in1,6,9);
    % 3）插值到每日
    data_in2 = interp1(date_sg,data_sg,date_in,"linear");
    % 4）剔除原始数据中间隔30天以上的插值数据
    f2 = ~isnan(data) & date>=date_start & date<=date_end;
    date_vali = date(f2);
    cut = date_vali(1,2:end) - date_vali(1,1:end-1);
    f3 = find(cut>30); %大于30天间隔的数据
    date_start = date_vali(f3);
    date_end = date_vali(f3+1);
    for i = 1:length(date_start)
        a = date_start(i);
        b = date_end(i);
        data_in2(date_in>a & date_in<b) = nan;
    end
    % 5)output
    data_in = data_in2;
end
