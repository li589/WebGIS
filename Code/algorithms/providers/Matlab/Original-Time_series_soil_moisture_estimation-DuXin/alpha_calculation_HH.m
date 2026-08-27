%% alpha simulation function
%HH chanel
function [alpha_sim_hh]=alpha_calculation_HH(theta,epsilon)
    A_a = epsilon-1;
    denominator_hh = power(  (cos(theta)+sqrt(epsilon-power(sin(theta),2))),2);
    alpha_sim_hh = abs(A_a/denominator_hh);
end

