function Func = F_h(x,Tbv,Tbh,Ts,Tau_ini,CF,Albedo,Freq,Theta)
% Cost function to retrieve soil moisture
SM = x(1);
h = x(2);
% Soil dielectric constant
eps = Mironov(Freq,SM,CF);
% Smooth soil reclectance
[rh, rv] = Fresnel(Theta,eps);
% Rough soil reflectance
Q = 0.1771.*h;
rh_r = ((1-Q).*rh + Q.*rv).* exp(-h.*cosd(Theta).^2);
rv_r = ((1-Q).*rv + Q.*rh).* exp(-h.*cosd(Theta).^2);
% transmissivity of canopy layer
% gamma = exp(-Tau_ini.*secd(Theta));
gamma = exp(-Tau_ini); %在计算Tau时进行过角度矫正
% Tb modeled: Eq.(1)
Tbv_m = Ts.*((1-rv_r).*gamma + (1-Albedo).*(1-gamma ).*(1+rv_r.*gamma));
Tbh_m = Ts.*((1-rh_r).*gamma + (1-Albedo).*(1-gamma ).*(1+rh_r.*gamma));
% Cost function: Eq.(5)
Func = [...
    Tbv_m - Tbv;...
    Tbh_m - Tbh];
end
