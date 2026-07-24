function [SM,VOD] = DDCA(Tbv,Tbh,Ts,Tau_ini,H,CF,Albedo,porosity,Freq,Theta)
% retrieve soil moisture
[m,n] = size(Tbv);
SM = nan(size(Tbv));
VOD = nan(size(Tbv));
parfor p = 1:m
    for q = 1:n
        if isnan(Tbv(p,q)) || isnan(Tbh(p,q)) || isnan(Ts(p,q)) || isnan(Tau_ini(p,q)) ...
                || isnan(H(p,q))|| isnan(CF(p,q)) || isnan(Albedo(p,q)) || isnan(porosity(p,q)) ...
                || isnan(Theta(p,q))
            continue;
        end
        options = struct(); options.Display = 'off';
        func = @(x)F_sm(x,Tbv(p,q),Tbh(p,q),Ts(p,q),Tau_ini(p,q),H(p,q),CF(p,q),Albedo(p,q),Freq,Theta(p,q));
        temp_retr = lsqnonlin(func,[0.2;0.5],[.02,0],[porosity(p,q),5],options);
        temp_retr = real(temp_retr);
        SM(p,q)  = temp_retr(1);
        VOD(p,q) = temp_retr(2);
    end
end
