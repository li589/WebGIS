function DH = Retrieve_DH(Tbv,Tbh,Ts,Tau_ini,CF,Albedo,porosity,Freq,Theta)
% Retrieve dynamic h
[m,n] = size(Tbv);
DH = nan(m,n);
parfor p = 1:m
    for q = 1:n
        if isnan(Tbv(p,q)) || isnan(Tbh(p,q)) || isnan(Ts(p,q)) || isnan(Tau_ini(p,q)) ...
                || isnan(CF(p,q)) || isnan(Albedo(p,q)) || isnan(porosity(p,q))|| isnan(Theta(p,q))
            continue;
        end
        options = struct(); options.Display = 'off';
        func = @(x)F_h(x,Tbv(p,q),Tbh(p,q),Ts(p,q),Tau_ini(p,q),CF(p,q),Albedo(p,q),Freq,Theta(p,q));
        temp_retr = lsqnonlin(func,[0.2;0.5],[.02,0],[porosity(p,q),3],options);
        temp_retr = real(temp_retr);
        temp_retr = temp_retr(2);
        DH(p,q)  = temp_retr;
    end
end
