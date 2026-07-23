function [rh,rv] = Fresnel(Theta,eps)
% Fresnel function
% rp: surface reflectance at p polization
% Theta: incidant angle
% eps: soil eps constant
x = sqrt(eps-sind(Theta).^2);
rh = abs((cosd(Theta)-x) ./ (cosd(Theta)+x)) .^2;
rv = abs((eps*cosd(Theta)-x) ./ (eps*cosd(Theta)+x)) .^2;
end
