%Child function of the 'Fun_time_series_SME_hh'
%Estimate the 'alpha' value of each slide window
%Inputs:
%-incidence angle (in darian): inc_ang
%-size of the image: 'rows','cols'
%-sliding window size: 'Num_step'
%-observations data of each slide window: 'multi_temporal_data'
%-defininition of observation matrix: 'MPP'
%-expected solution vector: 'Zero_solv'  (MPP.*soil_alpha_retrieval=Zero_solv)
%Outputs:
%-estimated 'alpha' value of each slide window: 'soil_alpha_retrieval'
function [soil_alpha_retrieval] = Fun_soil_alpha_retrieval_hh(rows,cols,Num_step,...
    inc_ang,multi_temporal_data,MPP,Zero_solv)

% Define the waitbar to show the processing process
waitbar_mesage=strcat('Please wait,it is caculating the $Alpha$ value!');
h = waitbar(0,waitbar_mesage);

% estimated alpha value of each observation date
soil_alpha_retrieval=zeros(rows,cols,Num_step);

%Introductions of MPP
%  ----                                             ---- 
% | 1   -S1/S2       0       .      .     .     0       |
% | 0      1      -S2/S3     .      .     .     .       |
% | 0      0         1    -S3/S4    .     .     .       |
% | .      .         .       .      .     .     .       |
% | .      .         .       .      .     .     .       |
% | .      .         .       .      .     .     .       |
% | 0      .         .       .      .     1  -S(N-1)/SN |
%  ----                                             ----   (N-1)*N
for ii = 1:1:rows
    for jj= 1:1:cols
        %create MPP observation matrix
        for kk=1:1:Num_step-1
            MPP(kk,kk)=1;
            MPP(kk,kk+1)=-sqrt(multi_temporal_data(ii,jj,kk)/...
                multi_temporal_data(ii,jj,kk+1));
        end
        
        %define the soil dielectric constant bounds
        epsilon_min=4;
        epsilon_max=35;
        
        %low and up bound of corespond alpha coefficients
        lb=abs(double(ones(Num_step,1))*...
            alpha_calculation_HH(inc_ang(ii,jj),epsilon_min));
        ub=abs(double(ones(Num_step,1))*...
            alpha_calculation_HH(inc_ang(ii,jj),epsilon_max));      
        lb=double(lb);
        ub=double(ub);
        
        %Solving the undetermined linear least squared regression problem
        %MPP.*Alpha_simulation=Zero_solv';
        %Get solution of the alpha 
        options = optimset('lsqlin');
        options.Algorithm = 'interior-point';
        
        %results of Num_step alpha estimation
        x = lsqlin(MPP,Zero_solv,[],[],[],[],lb,ub,[],options);
        soil_alpha_retrieval(ii,jj,:)=x;
    end
    waitbar(ii/rows);
end
close(h); %close the wait bar
end
