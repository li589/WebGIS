%Main program of soil moisture estimation algorithm
%Input time series data and incidence angle
%'Time_series_SME'Time series soil moisture estimation fucntion
%--Input parameters:
%1)obsv_data:
%  observ_data (backscatter coefficient,not in 'dB' unit);
%  stacked time series SAR images- 3 dimensional matrix;
%2)inc_ang:
%  incidence angle (unit in radian);
%  2 dimensional matrix,
%--Output parameters:
%1)volumetric soil moisture (mv%)
clc;
clear;

%% ######################Part 0: Input data###############################%
%Generate random simulated data:
%-obsv_data:time series SAR observations
%-inc_ang:incidence angle
obsv_data = rand(20,20,14);%20rows*20cols*14bands, 14 imageries,range:[0,1]
a=0.3;%minimum incidence angle 17degree
b=1.2;%maximum incidence angle 69degree
inc_ang = a + (b-a).*rand(20,20);%radian unit,range:[0.3,1.2]

[rows, cols,Num_image]=size(obsv_data);
Num_step= Num_image;%size of sliding windows

soil_epsilon_retrieval = zeros(20,20,14);
%soil_alpha_retrieval = zeros(20,20,14);
%soil_moisture_retrieval = zeros(20,20,14);% define volumetric

%% #################### Part-1: Caculate the 'alpha' value  ############# %
%Caculate the 'alpha' value from time series observations
%for HH chanel
soil_alpha_retrieval = Fun_time_series_SME_hh(obsv_data,inc_ang,Num_step);

%for VV chanel
%soil_alpha_retrieval = Fun_time_series_SME_vv(obsv_data,inc_ang,Num_step);

soil_alpha_retrieval(isinf(soil_alpha_retrieval)|isnan(soil_alpha_retrieval)) = 0;
% Replace NaNs and infinite values with zeros

%% ###Part-2:Caculate the soil dielectric constant from 'alpha' value#### %
%% #################### Part-2.1: Create lookup tables ################## %
%------------------ Fresnel coeeficients caculation-----------------------#
C_alpha_HH=zeros(901,311);% incidence, epsilon
C_alpha_VV=zeros(901,311);
B_epsilon=4:0.1:35;%311 elements
A_thetai=0.3:0.001:1.2;%901 elements
for ii=1:1:311
    for jj=1:1:901
        C_alpha_HH(jj,ii)=alpha_calculation_HH(A_thetai(jj),B_epsilon(ii));
        C_alpha_VV(jj,ii)=alpha_calculation_VV(A_thetai(jj),B_epsilon(ii));
    end
end

%% ###### Part-2.2: Lookup table reverse, obtain the 'epsilon' ########## %
%Find the dielectric constant which is coreesponded to ...
%the observed Fresnel coefficients
waitbar_mesage=strcat('Please wait few minutes,it is creating Lookup table!');
h = waitbar(0,waitbar_mesage);
for ii = 1:1:rows
    for jj= 1:1:cols
        for kk=1:1:Num_image
            A1=double(inc_ang(ii,jj));

            %for HH chanel
            Z=interp2(A_thetai',B_epsilon,C_alpha_HH',A1,B_epsilon);
            %%for VV chanel
            %Z=interp2(A_thetai',B_epsilon,C_alpha_VV',A1,B_epsilon);
            C1=soil_alpha_retrieval(ii,jj,kk);

            %solved soil dielectric constant value
            soil_epsilon_retrieval(ii,jj,kk)=interp1(Z,B_epsilon,C1);
        end
    end
    waitbar(ii/rows);
end
close(h); %close the wait bar

%reset invalid value to 0
soil_epsilon_retrieval(isnan(soil_epsilon_retrieval)==1)=0;

%% ##Part 3: convert soil dielectric constant to volumetric soil moisture##%
%%Topp model-1980; TOPP model
soil_moisture_retrieval = -5.3 + 2.92 .* soil_epsilon_retrieval -...
    0.055 .* soil_epsilon_retrieval .* soil_epsilon_retrieval +...
    0.0004 .* soil_epsilon_retrieval .* soil_epsilon_retrieval .* soil_epsilon_retrieval;
soil_moisture_retrieval(soil_epsilon_retrieval==0)=0;%reset invalid value 0
