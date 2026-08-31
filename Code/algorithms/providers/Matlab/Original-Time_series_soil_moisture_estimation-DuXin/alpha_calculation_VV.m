%% alpha simulation function
%VV chanel
function [alpha_sim_vv]=alpha_calculation_VV(theta,epsilon)
    B_a = (epsilon-1)*(power(sin(theta),2)-epsilon*(1+power(sin(theta),2)));
    denominator_vv = power(epsilon*(cos(theta))+sqrt(epsilon-power(sin(theta),2)),2);
    alpha_sim_vv = abs(B_a/denominator_vv);
end
