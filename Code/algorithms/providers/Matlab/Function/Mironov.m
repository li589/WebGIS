function eps = Mironov(Freq,SM,CF)
% Mironov's soil dielectric model
% eps: soil dielectric constant
% Freq: frequency of microwave radiometer
% SM: soil moisture
% CF: clay fraction
eps_0 = 8.854e-12;
eps_winf = 4.9;
fHz = Freq*1e9;
% Initializing the GRMDM spectroscopic parameters with clay fraction
% RI & NAC of dry soils
znd = 1.634 - 0.539 * CF + 0.2748 * CF.^2;
zkd = 0.03952 - 0.04038 * CF;
% Maximum bound water fraction
zxmvt = 0.02863 + 0.30673 * CF;
% Bound water parameters
zep0b = 79.8 - 85.4 * CF + 32.7 * CF.^2;
ztaub = 1.062e-11 + 3.450e-12 * CF;
zsigmab = 0.3112 + 0.467 * CF;
% Unbound (free) water parameters
zep0u = 100;
ztauu = 8.5e-12;
zsigmau = 0.3631 + 1.217 * CF;
% Computation of epsilon water (bound & unbound)
zcxb = (zep0b - eps_winf) ./ (1 + (2*pi*fHz*ztaub).^2);
zepwbx = eps_winf + zcxb;
zepwby = zcxb .* (2*pi*fHz*ztaub) + zsigmab ./ (2*pi*eps_0*fHz);
zcxu = (zep0u - eps_winf) ./ (1 + (2*pi*fHz*ztauu).^2);
zepwux = eps_winf + zcxu;
zepwuy = zcxu .* (2*pi*fHz*ztauu) + zsigmau ./ (2*pi*eps_0*fHz);
% Computation of refractive index of water (bound & unbound)
znb = sqrt( sqrt( zepwbx.^2 + zepwby.^2) + zepwbx ) / sqrt(2);
zkb = sqrt( sqrt( zepwbx.^2 + zepwby.^2) - zepwbx ) / sqrt(2);
znu = sqrt( sqrt( zepwux.^2 + zepwuy.^2) + zepwux ) / sqrt(2);
zku = sqrt( sqrt( zepwux.^2 + zepwuy.^2) - zepwux ) / sqrt(2);
% Computation of soil refractive index (nm & km): xmv can be a vector
zxmvt2 = min(SM,zxmvt);
zflag = double(SM >= zxmvt);
znm = znd + (znb - 1) .* zxmvt2 + (znu - 1) .* (SM-zxmvt) .* zflag;
zkm = zkd + zkb .* zxmvt2 + zku .* (SM-zxmvt) .* zflag;
% Computation of soil dielectric constant:
zepmx = znm.^2 - zkm.^2;
zepmy = znm .* zkm * 2;
eps = zepmx + i*zepmy;
end
