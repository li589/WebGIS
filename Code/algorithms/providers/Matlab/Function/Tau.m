function Tau_ini = Tau(NDVI,NDVI_max,NDVI_min,Landcover,b,sf,theta)
% This function for culculating the tau
% NDVI: Dynamic NDVI
% NDVI_max: max NDVI yearly
% NDVI_min: min NDVI yearly
% Landcover: Landcover class based on IGBP
% b: vegetation parameters in Eq.(2)
% df: stem factor in Eq (3)
% theta: incident angle

% 1. CaLandcoverulate VWC
NDVI(NDVI<0 | NDVI>1) = nan;
[m,n] = size(NDVI);
VWC2 = zeros(m,n);
VWC1 = 1.9134*(NDVI.^2) - 0.3215*NDVI;
% 10,12: grassland and cropland
VWC2(Landcover == 10 | Landcover ==12) = sf(Landcover == 10 | Landcover ==12) ./ (1-NDVI_min(Landcover == 10 | Landcover ==12)) ...
    .* (NDVI(Landcover == 10 | Landcover ==12)-NDVI_min(Landcover == 10 | Landcover ==12));
% 0-water
VWC2(Landcover==0) = nan;
% other  10农田12草地
VWC2(Landcover ~= 10 & Landcover ~=12) = sf(Landcover ~= 10 & Landcover ~=12) ./ (1-NDVI_min(Landcover ~= 10 & Landcover ~=12)) ...
    .* (NDVI_max(Landcover ~= 10 & Landcover ~=12)-NDVI_min(Landcover ~= 10 & Landcover ~=12));
% all
VWC = VWC1 + VWC2;
VWC(VWC>30 | isinf(VWC)) = nan;
% 2. Calculate Tau
Tau_ini = b .* VWC .* secd(theta);
Tau_ini(Tau_ini<0 | Tau_ini>5) = nan;
end
