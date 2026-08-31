%'Time_series_SME'Time series soil moisture estimation fucntion
%--References:?
%[1] J. D. Ouellette et al., ¡®A Time-Series Approach to Estimating Soil ...
%    Moisture from Vegetated Surfaces Using L-Band Radar Backscatter¡¯, ...
%    IEEE Trans. Geosci. Remote Sens., vol. 55, no. 6, pp. 3186?3193, 2017.
%[2]?A. Balenzano, F. Mattia, G. Satalino, and M. W. J. Davidson, ¡®Dense ...
%    Temporal Series of C- and L-band SAR Data for Soil Moisture Retrieval ...
%    Over Agricultural Crops¡¯, IEEE J. Sel. Top. Appl. Earth Obs. Remote ...
%    Sens., vol. 4, no. 2, pp. 439?450, Jun. 2011.
%--Input parameters:
%1)obsv_data:
%  observ_data (backscatter coefficient,not in 'dB' unit);
%  stacked time series SAR images- 3 dimensional matrix;
%2)inc_ang:
%  incidence angle (unit in radian);
%  2 dimensional matrix,
%--Output parameters:
%1)soil_alpha_retrieval_win_average

function [soil_alpha_retrieval_win_average]=Fun_time_series_SME_hh(obsv_data,inc_ang,Num_step)
[rows,cols,bds] = size(obsv_data); % 'bds' equal to the value of time-series N
%[rows,cols] = size(inc_ang); %'inc_ang' has same size area with 'obsv_data'
Num_image=bds;

%Num_step=4;%slide windows size
M=Num_image-Num_step+1;%M steps for Num_images time series retrieval

soil_alpha_retrieval_step_M=zeros(rows,cols,Num_step,M);%total M-steps results
soil_alpha_retrieval_step_i=zeros(rows,cols,Num_step);% step-i results

%restore the sliding windows
  for ii=1:1:M
      multi_temporal_data=obsv_data(:,:,(ii:ii+Num_step-1));
      MPP=zeros(Num_step-1,Num_step);%Define MPP matrix of observations

      Zero_solv=zeros((Num_step-1),1);% expected solution result

      %caculate the 'alpha' value from time series observations for each slide window
      soil_alpha_retrieval_step_i=Fun_soil_alpha_retrieval_hh(rows,cols,Num_step,...
          inc_ang,multi_temporal_data,MPP,Zero_solv);

      % store 'alpha' value from time series observations for M step windows
      soil_alpha_retrieval_step_M(:,:,:,ii)=soil_alpha_retrieval_step_i;
  end

  %reset invalid value to zero
  soil_alpha_retrieval_step_M(isnan(soil_alpha_retrieval_step_M)==1)=0;

  %Create an matrix to store the M-step results of each date
  soil_alpha_retrieval_time_series=zeros(rows,cols,Num_image,M);
  for ii=1:1:M
    soil_alpha_retrieval_time_series(:,:,ii:((ii-1)+Num_step),ii)=...
        soil_alpha_retrieval_step_M(:,:,1:Num_step,ii);
  end

  %reset the invalid value to NaN
  soil_alpha_retrieval_time_series(soil_alpha_retrieval_time_series==0)=NaN;

  %caculate the average of M-steps result of each date
  soil_alpha_retrieval_win_average=nanmean(soil_alpha_retrieval_time_series,4);

end
