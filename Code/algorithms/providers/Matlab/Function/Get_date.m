function datelist = Get_date(namelist)
% GET_DATE
% This function for getting the date of the namelist like "yyyymmdd"
    len = length(namelist);
    for i = 1:len
        date = namelist(i).name(1:8);
        datelist(i,:) = datetime(date,"InputFormat",'yyyyMMdd');
    end
end
