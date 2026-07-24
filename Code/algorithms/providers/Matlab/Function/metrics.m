function [r,rmse,ubrmse,bias,p] = metrics(x,y)
% 用于计算统计值R，RMSE,UBRMSE,BIAS
% x: 预测值
% y: 实测值
% n = length(x);

[r,p] = corrcoef(x,y,"Alpha",0.05);
r = r(1,2);
p = p(1,2);
rmse = sqrt(mean((x-y) .^2));
bias = mean(x-y);
ubrmse = sqrt(rmse^2 - bias^2);
end
