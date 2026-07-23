%记得每年分开计算才是YH

%比final 多了：
%NDVI 可以走 daily file，也可以走 DOY climatology
%SF 可以走静态 SF，也可以走基于 SMAP vwc + NDVI_clim 的逐日反推 SF
%Tau 的 VWC2 公式也变成两种模式可切换
%SF 可以走静态 SF，也可以走基于 SMAP vwc + NDVI_clim 的逐日反推 SF
%Tau 的 VWC2 公式也变成两种模式可切换
function OMEGA_IDENT_FAST()
clc; warning('off','backtrace');

% ===== 主进程限制线程 + 底层库线程 =====
try, maxNumCompThreads(1); catch, end
setenv('OMP_NUM_THREADS','1');
setenv('MKL_NUM_THREADS','1');
setenv('OPENBLAS_NUM_THREADS','1');
setenv('VECLIB_MAXIMUM_THREADS','1');

tAll = tic;

%% ==================== 配置 ====================
CFG.start_date = '20250101';
CFG.end_date   = '20251231';

CFG.func_dir       = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAcode/2.Code/Function/';
CFG.smap_folder    = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAPdata/MAT/';
CFG.fy3d_folder = '/public/shared_data/Chenhaojun/FY3D_output/matfinalfinal/';
CFG.fy3b_folder = '/public/shared_data/Chenhaojun/FY3Bmat/';

% ===== 新增：sf 方案 =====
CFG.SF_MODE = "INVERTED_DAILY";   % "STATIC" | "INVERTED_DAILY"

% ===== 新增：SF 倒推公式模式 =====
% "POINT1"  : 用 (NDVI_ref - 0.1)/0.9
% "NDVIMIN" : 用 (NDVI_ref - NDVI_clim_min)/(1 - NDVI_clim_min)
CFG.SF_INVERT_MODE = "POINT1";   % "POINT1" | "NDVIMIN"

% ===== 新增：静态 NDVI climatology（按 DOY 1~366 命名）=====
CFG.ndvi_clim_folder  = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/NDVI_clim/';
CFG.ndvi_clim_varname = 'NDVI_clim';

% ===== 新增：后续 Tau/反演所用 NDVI 方案 =====
% 只控制 SF 反推完成之后，后面 Tau、low-tau、h/alpha、omega、SM/VOD 用的 NDVI
% 不影响 SF_MODE="INVERTED_DAILY" 时反推 sf 所使用的 NDVI_clim
CFG.NDVI_MODE = "DOY_CLIM";   % "DAILY_FILE" | "DOY_CLIM"

CFG.ndvi_doy_clim_start_year = 2015;
CFG.ndvi_doy_clim_end_year   = 2025;
CFG.ndvi_doy_clim_min_count  = 1;

% ===== 新增：Tau 中 VWC2 的公式模式 =====
% "NDVIMIN" : 用 (1 - NDVI_min) 归一化，和你现在代码一致
% "POINT1"  : 用 (NDVI_ref - 0.1)/0.9 归一化，即 0.1 公式
CFG.TAU_VWC2_MODE = "POINT1";   % "NDVIMIN" | "POINT1"

CFG.ndvi_folder    = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/VNP13C1002/4.Daily/';
CFG.anc_root       = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/';
CFG.ismn_grid_file = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/DCA_VI_H/Validation/ismn_5cm/ismn_grid.mat';
% CFG.gldas_template_file = '/share/home/user03/Chenhaojun/output/GLDAS_UTC_TEMPLATE/gldas_utc_template_global.mat';
CFG.USE_GLDAS_TEMPLATE = true;
CFG.SAVE_MATCH_INFO = false;
% ===== DDCA SM 文件夹（每日 yyyymmdd.mat，变量名 SM）=====
 CFG.ddca_sm_folder = '/share/home/user03/Chenhaojun/YH/SM/';

% ===== 新增：GLDAS 温度文件夹 =====
 CFG.gldas_mat_folder = '/share/home/user03/Chenhaojun/GLDASmat/';

% ===== 运行域选择 =====
CFG.RUN_DOMAIN = "GLOBAL";   % "ISMN" | "GLOBAL"

% ===== 数据源开关 =====
CFG.TB_SOURCE = "FY";      % "FY" | "SMAP"

% ===== SM_SOURCE =====
CFG.SM_SOURCE = "SMAP";    % "SMAP" | "ISMN" | "DDCA"   (GLOBAL 时不能 ISMN)

CFG.FY_PLATFORM = "3D";   % "3D" | "3B"
CFG.MATCH_ENABLE = true;
CFG.MATCH_METHOD = "bias";    % "none" | "bias" | "cdf"
CFG.match_fy3b_folder = CFG.fy3b_folder;
CFG.match_fy3d_folder = CFG.fy3d_folder;
CFG.match_start_date = '20190101';
CFG.match_end_date   = '20191231';
CFG.match_min_valid_n = 20;
CFG.MATCH_CDF_EXTRAP  = true;

% ===== 当 TB_SOURCE="SMAP" 时，h/Q 的处理方式 =====
% "LOWTAU"          : 原逻辑（低τ反演 h*,alpha*）
% "YEARFILE_HQFIX"  : 读每年一张 h 图，不再反演 h/Q；Q 固定为 CFG.Q_FIXED
CFG.SMAP_HQ_MODE     = "LOWTAU";        % "LOWTAU" | "YEARFILE_HQFIX"
CFG.h_year_folder    = '/share/home/user03/Chenhaojun/YH/H/';
CFG.h_year_pattern   = 'YH_%d.mat';
CFG.h_year_varname   = 'YH';
CFG.Q_FIXED          = 0.1771;

% ===== 任务列表模式（仅 RUN_DOMAIN=ISMN 时有效）=====
CFG.LIST_MODE   = 'ISMN_ALL';   % 'CSV' | 'ISMN_ALL'
CFG.station_csv = '';

% ===== 只跑指定 key（可关闭）=====
CFG.target_keys_enable = false;
CFG.target_keys = strings(0,1);

% ===== 实验模式 =====
CFG.EXP = "Exp0";             % "Exp0" | "Exp1a" | "Exp1b" | "Exp2"

% ===== Tb 坏点删除（可作用于 FY / SMAP / ALL）=====
CFG.SPIKE.enable = true;
CFG.SPIKE.apply_to = "ALL";   % "FY" | "SMAP" | "ALL" | "NONE"
CFG.SPIKE.default_TBv_thr = 25;
CFG.SPIKE.default_TBh_thr = 25;
CFG.SPIKE.station_keys    = strings(0,1);
CFG.SPIKE.station_TBv_thr = [];
CFG.SPIKE.station_TBh_thr = [];

% ===== 新增：温度方案 =====
% "ORIG_TS"：保持原逻辑，直接从原文件读 Ts，不做 GLDAS 匹配
% "DUAL"   ：GLDAS 三层温度匹配 -> TC/Tsoil1/Tsoil2 -> Ct/TG 双温度方案
CFG.TEMP_SCHEME = "ORIG_TS";    % "ORIG_TS" | "DUAL"

% 单温度来源（保持原逻辑）
% SMAP 路：直接读当日 SMAP 文件中的 Ts
% FY   路：直接读当日 SMAP 文件中的 Ts（作为 FY 单温度方案的 Ts）
CFG.TS_SOURCE         = "ORIG_FILE_TS";
CFG.SINGLE_TS_SOURCE  = "ORIG_FILE_TS";

% 双温度来源
CFG.DUAL_TC_SOURCE = "GLDAS_TC";
CFG.DUAL_TG_MODE   = "PAPER_CT";    % "PAPER_CT" | "TSOIL1_ONLY" | "TSOIL2_ONLY"

CFG.CT_SMREF = 0.30;
CFG.CT_EXP   = 0.30;

CFG.fy3d_desc_local_hour = 2.0;
CFG.fy3b_desc_local_hour = 1 + 40/60;
CFG.smap_desc_local_hour = 6.0;
CFG.gldas_time_tol_hours = 1.6;

CFG.gldas_var_TC     = 'Ts_gldas';
CFG.gldas_var_Tsoil1 = 'Tsoil1_gldas';
CFG.gldas_var_Tsoil2 = 'Tsoil2_gldas';

% ===== 候选筛选 =====
CFG.n_per_class      = 5;
CFG.random_seed      = 42;
CFG.exclude_classes  = [];
CFG.ismn_min_days    = 30;
CFG.ISMN_ALL_RUNMODE = "ALL";      % "ALL" | "SAMPLE"

CFG.GLOBAL_RUNMODE = "ALL";        % "ALL" | "SAMPLE"
CFG.global_n       = 50000;
CFG.global_seed    = 42;

% ===== 分片 =====
SHARD.ENABLE = true;
SHARD.N      = 1;
SHARD.ID     = 1;
SHARD.MODE   = 'roundrobin';   % 'roundrobin' | 'contiguous'

% ===== 并行 =====
% CFG.PAR_SAVE.ENABLE      = true;
% CFG.PAR_SAVE.NUM_WORKERS = [];
% CFG.PAR_SAVE.MAX_WORKERS = inf;
% ===== 并行 =====
CFG.PAR_SAVE.ENABLE      = true;
CFG.PAR_SAVE.NUM_WORKERS = 56;%%%%%%%%%%
CFG.PAR_SAVE.MAX_WORKERS = 56;%%%%%%%%%%
CFG.PAR_SAVE.CHUNK_SIZE  = 200000;   % 每次只预读/反演 20 万像元

% ===== 输出 =====
CFG.out_root = '/public/home/liuzh535/output/fy_single_2025_2point_sf';
CFG.out_mat  = fullfile(CFG.out_root,'mat');
CFG.out_aux  = fullfile(CFG.out_root,'aux_data');
CFG.out_block = fullfile(CFG.out_root,'block_mat');

if ~exist(CFG.out_root,'dir'), mkdir(CFG.out_root); end
if ~exist(CFG.out_mat,'dir'),  mkdir(CFG.out_mat);  end
if ~exist(CFG.out_aux,'dir'),  mkdir(CFG.out_aux);  end
if ~exist(CFG.out_block,'dir'),mkdir(CFG.out_block);end

CFG.ndvi_cache_dir = fullfile(CFG.out_aux,'ndvi_cache');
if ~exist(CFG.ndvi_cache_dir,'dir'), mkdir(CFG.ndvi_cache_dir); end

CFG.OMEGA_FIXED_MODE = "PFT";   % "PFT" | "PIXEL"
CFG.omega_pft_file = fullfile(CFG.out_aux,'omega_pft_from_exp0.mat');
CFG.omega_pix_file = fullfile(CFG.out_aux,'omega_pixel_from_exp0.mat');

CFG.exp0_calib_dir = fullfile(CFG.out_aux,'exp0_calib');
if ~exist(CFG.exp0_calib_dir,'dir'), mkdir(CFG.exp0_calib_dir); end

CFG.WEIGHT_MODE  = "EQUAL";
CFG.weights_file = fullfile(CFG.out_aux,'weights_from_exp0.mat');

CFG.lambda_list = 10.^(0:6);
CFG.lambda_star_override = NaN;
CFG.DAILY_USE_SINGLE = true;
% ===== 频率 =====
freq_GHz = 1.41;
if upper(string(CFG.TB_SOURCE))=="FY"
    freq_GHz = 10.65;
end

% ===== 默认角度（仅兜底）=====
theta_default = NaN;

% ===== 反演参数 =====
TAU_REL_FRAC  = 0.05;
KMIN          = 2;%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
ALPHA0        = 0.1771;
LAMBDA_ALPHA  = 1.0;
BOUNDS_H      = [0, 3];
BOUNDS_ALPHA  = [0.05, 0.35];
OMEGA0        = 0.12;
BOUNDS_OMEGA  = [0, 1];
LAMBDA_SMOOTH = 1;
LAMBDA_TAU    = 20;
CFG.block_days = 8;

% ===== QC：保留原输出结构 =====
CFG.QC_ENABLE        = true;
CFG.QC_NMIN          = 3;
CFG.QC_COND_THR      = 1e6;
CFG.QC_SMIN_REL_THR  = 1e-6;
CFG.QC_DOMEGA        = 1e-3;
CFG.QC_DTAU          = 1e-2;
CFG.QC_DH            = 1e-2;

% ===== 打印节奏 =====
CFG.PRINT_EVERY_DAYS = 20;

addpath(CFG.func_dir);

fprintf('\n============================================================\n');
fprintf('[START] OMEGA_IDENT_FAST\n');
fprintf('[TIME ] %s\n', datestr(now,'yyyy-mm-dd HH:MM:SS'));
fprintf('[RUN  ] EXP=%s | RUN_DOMAIN=%s | TB_SOURCE=%s | SM_SOURCE=%s\n', ...
    string(CFG.EXP), string(CFG.RUN_DOMAIN), string(CFG.TB_SOURCE), string(CFG.SM_SOURCE));

if upper(string(CFG.TB_SOURCE))=="FY"
    fprintf('[FY   ] PLATFORM=%s | MATCH_ENABLE=%d | MATCH_METHOD=%s\n', ...
        string(CFG.FY_PLATFORM), CFG.MATCH_ENABLE, string(CFG.MATCH_METHOD));
end

fprintf('[TEMP ] TEMP_SCHEME=%s | SINGLE_TS=%s | DUAL_TC=%s | DUAL_TG=%s\n', ...
    string(CFG.TEMP_SCHEME), string(CFG.SINGLE_TS_SOURCE), string(CFG.DUAL_TC_SOURCE), string(CFG.DUAL_TG_MODE));
fprintf('[FIXED] OMEGA_FIXED_MODE=%s\n', string(CFG.OMEGA_FIXED_MODE));
fprintf('[BLOCK] %d-day\n', CFG.block_days);
fprintf('============================================================\n');

%% ==================== 预备：并行池 ====================
PAR.ENABLE      = CFG.PAR_SAVE.ENABLE;
PAR.NUM_WORKERS = CFG.PAR_SAVE.NUM_WORKERS;
PAR.MAX_WORKERS = CFG.PAR_SAVE.MAX_WORKERS;
[usePar, pool] = setup_parpool(PAR);
if usePar
    fprintf('[PAR] 并行池：%d workers\n', pool.NumWorkers);
else
    fprintf('[PAR] 串行运行。\n');
end

%% ==================== 时间交集 ====================
tvec_req = datetime(CFG.start_date,'InputFormat','yyyyMMdd') : datetime(CFG.end_date,'InputFormat','yyyyMMdd');

T_smap = get_dates_from_folder(CFG.smap_folder);

if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"
    T_ndvi = get_dates_from_folder(CFG.ndvi_folder);
else
    T_ndvi = tvec_req;   % DOY_CLIM 模式下，不要求运行期当天 NDVI 文件存在
end

if upper(string(CFG.TB_SOURCE))=="FY"
    if upper(string(CFG.FY_PLATFORM))=="3D"
        T_tb = get_dates_from_folder(CFG.fy3d_folder);
    elseif upper(string(CFG.FY_PLATFORM))=="3B"
        T_tb = get_dates_from_folder(CFG.fy3b_folder);
    else
        error('未知 CFG.FY_PLATFORM=%s', string(CFG.FY_PLATFORM));
    end
else
    T_tb = T_smap;
end

% SM 参考时间
if upper(string(CFG.SM_SOURCE))=="DDCA"
    T_smref = get_dates_from_folder(CFG.ddca_sm_folder);
elseif upper(string(CFG.SM_SOURCE))=="SMAP"
    T_smref = T_smap;
else
    T_smref = tvec_req;
end

% 这里强制并入 T_smap，和源代码一致：
% 因为后面无论 Ts 还是 sm_dca，都是从 SMAP 日文件里读
T_base = intersect(tvec_req, T_tb);
T_base = intersect(T_base, T_smap);
T_base = intersect(T_base, T_ndvi);
T_base = intersect(T_base, T_smref);

GLDAS_INDEX = struct('files',[],'t_utc',NaT(0,1));
GLDAS_TEMPLATE = struct();
GLDAS_DAY_SLOT = struct();

if upper(string(CFG.TEMP_SCHEME))=="DUAL"
    GLDAS_INDEX = build_gldas_file_index(CFG.gldas_mat_folder);

    if isfield(CFG,'USE_GLDAS_TEMPLATE') && CFG.USE_GLDAS_TEMPLATE
    Sg = load(CFG.gldas_template_file);

    if upper(string(CFG.TB_SOURCE))=="FY"
        if upper(string(CFG.FY_PLATFORM))=="3D"
            GLDAS_TEMPLATE = Sg.FY3D_template;
        elseif upper(string(CFG.FY_PLATFORM))=="3B"
            GLDAS_TEMPLATE = Sg.FY3B_template;
        else
            error('未知 CFG.FY_PLATFORM=%s', string(CFG.FY_PLATFORM));
        end
    else
        GLDAS_TEMPLATE = Sg.SMAP_template;
    end

    GLDAS_DAY_SLOT = build_gldas_day_slot_table(GLDAS_INDEX);
end

    T_gldas_day = unique(dateshift(GLDAS_INDEX.t_utc,'start','day'));
    T_base = intersect(T_base, T_gldas_day);
end

tvec = dateshift(T_base,'start','day');
Nt = numel(tvec);
if Nt==0
    error('时间交集为空，请检查 TB/NDVI/SMref 以及（DUAL时）GLDAS 数据。');
end
fprintf('[INIT] 可用日期：%d（%s ~ %s）\n', Nt, datestr(tvec(1),'yyyy-mm-dd'), datestr(tvec(end),'yyyy-mm-dd'));

[blkStarts, blkEnds, blkIndexCell] = make_viirs8_blocks(tvec);

%% ==================== 静态库 ====================
S = load(fullfile(CFG.anc_root,'IGBP_9km_12.mat'));
assert(isfield(S,'IGBP_9km_12'), 'IGBP_9km_12.mat 缺少 IGBP_9km_12');
LC      = S.IGBP_9km_12;
lat_9km = pick_field(S,'lat_9km');
lon_9km = pick_field(S,'lon_9km');

Salb = load(fullfile(CFG.anc_root,'Albedo.mat')); ALBEDO = Salb.ALBEDO;
SB   = load(fullfile(CFG.anc_root,'B.mat'));      B      = SB.B;
SSF  = load(fullfile(CFG.anc_root,'SF.mat'));     SF_static = SSF.SF_smap;
Sbd  = load(fullfile(CFG.anc_root,'BD.mat'));     BD     = Sbd.BD;
Sh   = load(fullfile(CFG.anc_root,'H.mat'));      H      = Sh.H;
Scf  = load(fullfile(CFG.anc_root,'CF.mat'));     CF     = Scf.CF;

Smm = load('/public/shared_data/Chenhaojun/FYdata/VNP13C1002/5.MM/daily/1525/VI_v_qa.mat','NDVI_v_max','NDVI_v_min');
NDVI_v_max = Smm.NDVI_v_max;
NDVI_v_min = Smm.NDVI_v_min;

NDVI_clim_max = build_ndvi_clim_max(CFG.ndvi_clim_folder, CFG.ndvi_clim_varname);
NDVI_clim_min = build_ndvi_clim_min(CFG.ndvi_clim_folder, CFG.ndvi_clim_varname);

mask_static_ok = isfinite(ALBEDO) & isfinite(B) & isfinite(SF_static) & ...
                 isfinite(BD) & isfinite(H) & isfinite(CF) & ...
                 isfinite(NDVI_v_max) & isfinite(NDVI_v_min) & ...
                 isfinite(NDVI_clim_max) & isfinite(NDVI_clim_min);

%% ==================== ISMN grid ====================
needISMNgrid = upper(string(CFG.RUN_DOMAIN))=="ISMN" || upper(string(CFG.SM_SOURCE))=="ISMN";

grid = [];
grid_mesh_ismn = [];
grid_id = strings(0,1);
has_grid_latlon = false;
grid_lat = [];
grid_lon = [];
t_grid = [];

if needISMNgrid
    if upper(string(CFG.SM_SOURCE))=="ISMN"
        Sis = load(CFG.ismn_grid_file);
        assert(isfield(Sis,'grid_mesh') && isfield(Sis,'grid_id') && isfield(Sis,'grid'), ...
            'ismn_grid.mat 需包含 grid_mesh / grid_id / grid');
        grid           = Sis.grid;
        grid_mesh_ismn = Sis.grid_mesh(:);
        grid_id        = string(Sis.grid_id(:));
        has_grid_latlon = isfield(Sis,'grid_lat') && isfield(Sis,'grid_lon');
        if has_grid_latlon
            grid_lat = Sis.grid_lat(:);
            grid_lon = Sis.grid_lon(:);
        end
        if isfield(Sis,'t_grid')
            t_grid = Sis.t_grid(:);
            if isnumeric(t_grid), t_grid = datetime(t_grid,'ConvertFrom','datenum'); end
            t_grid = dateshift(t_grid,'start','day');
        else
            t0_ismn = datetime(2015,4,1);
            nDay = size(grid,2);
            t_grid = dateshift(t0_ismn + days(0:nDay-1), 'start','day');
        end
    else
        Sis = load(CFG.ismn_grid_file, 'grid_mesh', 'grid_id', 'grid_lat', 'grid_lon');
        assert(isfield(Sis,'grid_mesh') && isfield(Sis,'grid_id'), ...
            'ismn_grid.mat 需至少包含 grid_mesh / grid_id');
        grid_mesh_ismn = Sis.grid_mesh(:);
        grid_id        = string(Sis.grid_id(:));
        has_grid_latlon = isfield(Sis,'grid_lat') && isfield(Sis,'grid_lon');
        if has_grid_latlon
            grid_lat = Sis.grid_lat(:);
            grid_lon = Sis.grid_lon(:);
        end
    end
end

%% ==================== 构造任务列表 ====================
[network, station, st_lat, st_lon, keys, grid_mesh, preMapped] = build_task_list( ...
    CFG, LC, lat_9km, lon_9km, grid_mesh_ismn, grid_id, has_grid_latlon, grid_lat, grid_lon);
Nall = numel(keys);

%% ==================== 候选筛选 ====================
need_candidate_filter = true;
if CFG.target_keys_enable && upper(string(CFG.SM_SOURCE)) ~= "ISMN"
    need_candidate_filter = false;
end

if need_candidate_filter
    if upper(string(CFG.RUN_DOMAIN))=="ISMN" && upper(string(CFG.LIST_MODE))=="ISMN_ALL"
        [network, station, st_lat, st_lon, keys, grid_mesh, grid, grid_id, grid_lat, grid_lon] = ...
            filter_ismn_candidates(CFG, tvec, t_grid, grid, grid_id, grid_mesh, ...
            network, station, st_lat, st_lon, keys, ...
            LC, mask_static_ok, has_grid_latlon, grid_lat, grid_lon);
    end
else
    fprintf('[SELECT] 指定站点模式：跳过全量候选筛选。\n');
end

Nall = numel(keys);
fprintf('[SELECT] 候选筛选后任务数：%d\n', Nall);

%% ==================== 指定站点过滤 ====================
if CFG.target_keys_enable
    [network, station, st_lat, st_lon, keys, grid_mesh, grid, grid_id, grid_lat, grid_lon] = ...
        apply_target_key_filter(CFG, network, station, st_lat, st_lon, keys, grid_mesh, ...
        grid, grid_id, has_grid_latlon, grid_lat, grid_lon);
    Nall = numel(keys);
    fprintf('[KEY] 过滤后任务数：%d\n', Nall);
    if Nall==0
        error('target_keys 过滤后没有站点，请检查 CFG.target_keys 与 grid_id 是否完全一致。');
    end
else
    fprintf('[SELECT] 最终任务数：%d\n', Nall);
end

%% ==================== 分片 ====================
all_idx = (1:Nall).';
use_idx = all_idx;
if SHARD.ENABLE
    use_idx = shard_indices(all_idx, SHARD.N, SHARD.ID, SHARD.MODE);
end

network_use   = network(use_idx);
station_use   = station(use_idx);
lat_use       = st_lat(use_idx);
lon_use       = st_lon(use_idx);
keys_use      = keys(use_idx);
grid_mesh_use = grid_mesh(use_idx);

if upper(string(CFG.RUN_DOMAIN))=="ISMN" && upper(string(CFG.LIST_MODE))=="ISMN_ALL"
    grid_row_use = (1:numel(use_idx)).';
else
    grid_row_use = nan(numel(use_idx),1);
end

Nst = numel(use_idx);
shard_tag = sprintf('%s_%s_%s_shard%02dof%02d_%s', ...
    lower(char(CFG.EXP)), lower(char(CFG.RUN_DOMAIN)), lower(char(CFG.LIST_MODE)), ...
    SHARD.ID, SHARD.N, lower(char(SHARD.MODE)));
CFG.shard_tag = shard_tag;

%% ==================== 预映射 ====================
[iy_list, ix_list, cls_list, grid_row_list, map_warn] = premap_tasks( ...
    true, grid_mesh_use, grid_row_use, keys_use, lat_use, lon_use, ...
    LC, lat_9km, lon_9km, grid_id, grid_mesh_ismn, has_grid_latlon, grid_lat, grid_lon);
fprintf('[MAP] 本窗口映射完成：warn=%d / %d\n', map_warn, Nst);

if upper(string(CFG.SM_SOURCE))=="ISMN"
    badRow = ~isfinite(grid_row_list) | grid_row_list<1 | grid_row_list>size(grid,1);
    if any(badRow)
        ii = find(badRow,1,'first');
        error('[SM_SOURCE=ISMN] 有任务无法匹配到 ISMN grid 行号：s=%d key=%s。', ii, string(keys_use(ii)));
    end
end


lin_pix = sub2ind(size(LC), iy_list, ix_list);

%% =======================================================================
%% ==================== Chunk 分块预读 + 分块反演 ==========================
%% =======================================================================

% -----------------------------------------------------------------------
% 说明：
% 1) 不再一次性为全部像元预读 TB / NDVI / SMref / SF；
% 2) 改成每次只处理一个 chunk；
% 3) 每个 chunk 内部仍然 parfor 并行反演；
% 4) 最终 R_cell / fail_flag / fail_msg 仍然回填到完整总容器；
% 5) 最终输出仍然只有一个总 R 文件和一套 block_mat。
% -----------------------------------------------------------------------

if ~isfield(CFG.PAR_SAVE, 'CHUNK_SIZE') || isempty(CFG.PAR_SAVE.CHUNK_SIZE)
    CFG.PAR_SAVE.CHUNK_SIZE = 200000;
end

chunk_size = max(1, floor(CFG.PAR_SAVE.CHUNK_SIZE));
nChunk = ceil(Nst / chunk_size);

fprintf('[CHUNK] 启用单任务内部像元分块：CHUNK_SIZE=%d | nChunk=%d | 总像元=%d\n', ...
    chunk_size, nChunk, Nst);

%% ==================== NDVI DOY climatology 缓存准备 ====================
% 这里仍然保持"一个总缓存文件"，但正式反演时每个 chunk 只读自己的列。
% 如果缓存文件不存在，仍按原逻辑先构造一次总缓存。

ndvi_cache_file = '';
NDVI_DOY_CLIM_FILE = [];

if upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    if isempty(lin_pix)
        error('lin_pix 为空，无法构建 NDVI_DOY_CLIM 缓存。');
    end

    pix_hash  = sum(double(lin_pix(:)));
    pix_first = double(lin_pix(1));
    pix_last  = double(lin_pix(end));

    ndvi_cache_file = fullfile(CFG.ndvi_cache_dir, sprintf( ...
        'NDVI_DOY_CLIM_%d_%d_Npix%d_F%u_L%u_H%.0f.mat', ...
        CFG.ndvi_doy_clim_start_year, CFG.ndvi_doy_clim_end_year, ...
        numel(lin_pix), pix_first, pix_last, pix_hash));

    if exist(ndvi_cache_file, 'file') == 2
        fprintf('[NDVI] 检测到 DOY climatology 缓存，后续按 chunk 局部读取：%s\n', ndvi_cache_file);
    else
        fprintf('[NDVI] 缓存不存在，开始构建完整 DOY climatology: %d-%d\n', ...
            CFG.ndvi_doy_clim_start_year, CFG.ndvi_doy_clim_end_year);

        NDVI_DOY_CLIM = build_ndvi_doy_climatology_for_pixels(CFG, lin_pix);

        save(ndvi_cache_file, 'NDVI_DOY_CLIM', '-v7.3');
        fprintf('[NDVI] DOY climatology 已保存：%s\n', ndvi_cache_file);

        clear NDVI_DOY_CLIM
    end

    NDVI_DOY_CLIM_FILE = matfile(ndvi_cache_file);
end

%% ==================== 固定 omega 准备 ====================
omega_fixed_pft = [];
omega_fixed_pix = [];

if any(strcmpi(char(CFG.EXP), {'Exp1a','Exp1b','Exp2'}))
    if upper(string(CFG.OMEGA_FIXED_MODE))=="PFT"
        Sfix = load(CFG.omega_pft_file);
        if isfield(Sfix,'omega_pft')
            omega_fixed_pft = Sfix.omega_pft;
        else
            error('固定 PFT omega 文件缺少变量 omega_pft：%s', CFG.omega_pft_file);
        end
    else
        Sfix = load(CFG.omega_pix_file);
        if isfield(Sfix,'omega_pix_map')
            omega_fixed_pix = Sfix.omega_pix_map;
        else
            error('固定 PIXEL omega 文件缺少变量 omega_pix_map：%s', CFG.omega_pix_file);
        end
    end
end

%% ==================== 优化器 ====================
opts_halpha = optimoptions('lsqnonlin','Display','off','MaxIterations',400, ...
    'FunctionTolerance',1e-6,'StepTolerance',1e-6);

opts_om = optimoptions('lsqnonlin','Display','off','MaxIterations',400, ...
    'FunctionTolerance',1e-6,'StepTolerance',1e-6);

%% ==================== 进度队列 ====================
dq = [];
if usePar
    dq = parallel.pool.DataQueue;
    afterEach(dq, @(m) handle_msg(m, Nst, keys_use, shard_tag, CFG));
end

%% ==================== 总结果容器 ====================
R_cell     = cell(Nst,1);
fail_flag  = false(Nst,1);
fail_msg   = strings(Nst,1);

fprintf('[RUN] EXP=%s | RUN_DOMAIN=%s | TB_SOURCE=%s | SM_SOURCE=%s | TEMP_SCHEME=%s | 本窗口=%d\n', ...
    string(CFG.EXP), string(CFG.RUN_DOMAIN), string(CFG.TB_SOURCE), ...
    string(CFG.SM_SOURCE), string(CFG.TEMP_SCHEME), Nst);

[wV, wH] = get_weights(CFG);

%% =======================================================================
%% ==================== 外层：逐 chunk 预读并反演 ==========================
%% =======================================================================

for ic = 1:nChunk

    i1 = (ic-1)*chunk_size + 1;
    i2 = min(ic*chunk_size, Nst);
    idx_chunk = i1:i2;
    Nc = numel(idx_chunk);

    fprintf('\n============================================================\n');
    fprintf('[CHUNK] %d / %d | 全局序号 %d ~ %d | 当前像元数=%d\n', ...
        ic, nChunk, i1, i2, Nc);
    fprintf('============================================================\n');

    %% -------- 当前 chunk 的任务元数据 --------
    network_chunk   = network_use(idx_chunk);
    station_chunk   = station_use(idx_chunk);
    lat_chunk       = lat_use(idx_chunk);
    lon_chunk       = lon_use(idx_chunk);
    keys_chunk      = keys_use(idx_chunk);
    grid_mesh_chunk = grid_mesh_use(idx_chunk);

    iy_chunk        = iy_list(idx_chunk);
    ix_chunk        = ix_list(idx_chunk);
    cls_chunk       = cls_list(idx_chunk);
    grid_row_chunk  = grid_row_list(idx_chunk);
    lin_pix_chunk   = lin_pix(idx_chunk);

    %% -------- 当前 chunk 的静态像元参数，提前抽成一维向量 --------
    NDVI_v_max_chunk = NDVI_v_max(lin_pix_chunk);
    NDVI_v_min_chunk = NDVI_v_min(lin_pix_chunk);
    ALBEDO_chunk     = ALBEDO(lin_pix_chunk);
    B_chunk          = B(lin_pix_chunk);
    CF_chunk         = CF(lin_pix_chunk);
    BD_chunk         = BD(lin_pix_chunk);
    H_chunk          = H(lin_pix_chunk);

    %% -------- 当前 chunk 的 NDVI DOY climatology --------
    NDVI_DOY_CLIM_chunk = [];

    if upper(string(CFG.NDVI_MODE))=="DOY_CLIM"
        fprintf('[NDVI][CHUNK %d/%d] 读取当前 chunk 的 DOY climatology 列：%d ~ %d\n', ...
            ic, nChunk, i1, i2);

        NDVI_DOY_CLIM_chunk = NDVI_DOY_CLIM_FILE.NDVI_DOY_CLIM(:, idx_chunk);
    end

    %% -------- FY3B 匹配训练：按 chunk 做 --------
    MATCH_chunk = [];

    if upper(string(CFG.TB_SOURCE))=="FY" && upper(string(CFG.FY_PLATFORM))=="3B" ...
            && isfield(CFG,'MATCH_ENABLE') && CFG.MATCH_ENABLE ...
            && upper(string(CFG.MATCH_METHOD))~="NONE"

        fprintf('[MATCH][CHUNK %d/%d] 开始训练 FY3B->FY3D 匹配模型: method=%s\n', ...
            ic, nChunk, string(CFG.MATCH_METHOD));

        MATCH_chunk = build_match_models_for_pixels(CFG, lin_pix_chunk);

        fprintf('[MATCH][CHUNK %d/%d] 匹配训练完成。\n', ic, nChunk);
    else
        fprintf('[MATCH][CHUNK %d/%d] 跳过 FY 匹配训练。\n', ic, nChunk);
    end

    %% -------- 当前 chunk 预读 TB / SMref / NDVI / SF --------
    fprintf('[PRELOAD][CHUNK %d/%d] 开始预读 TB/SMref/NDVI', ic, nChunk);
    if upper(string(CFG.TEMP_SCHEME))=="DUAL"
        fprintf(' + GLDAS DUAL温度');
    else
        fprintf(' + 原始Ts');
    end
    fprintf(' ...\n');

    [TBv_mat, TBh_mat, IA_mat, Ts_mat, TC_mat, Tsoil1_mat, Tsoil2_mat, ...
     SMref_mat, NDVI_mat, SF_mat, MATCH_INFO] = ...
        preload_timeseries_merged( ...
            tvec, CFG, ...
            lin_pix_chunk, iy_chunk, ix_chunk, cls_chunk, lon_chunk, ...
            NDVI_clim_max, NDVI_clim_min, SF_static, ...
            GLDAS_INDEX, GLDAS_TEMPLATE, GLDAS_DAY_SLOT, ...
            t_grid, grid, grid_row_chunk, MATCH_chunk, NDVI_DOY_CLIM_chunk);

    fprintf('[PRELOAD][CHUNK %d/%d] 完成。\n', ic, nChunk);

    %% -------- 当前 chunk 的局部结果容器 --------
    R_cell_chunk     = cell(Nc,1);
    fail_flag_chunk  = false(Nc,1);
    fail_msg_chunk   = strings(Nc,1);

    %% -------- 当前 chunk 内部并行反演 --------
    if usePar

        parfor j = 1:Nc

            s_global = idx_chunk(j);

            [R_cell_chunk{j}, fail_flag_chunk(j), fail_msg_chunk(j)] = ...
                one_station_from_preloaded( ...
                    dq, s_global, ...
                    keys_chunk(j), network_chunk(j), station_chunk(j), ...
                    lat_chunk(j), lon_chunk(j), ...
                    iy_chunk(j), ix_chunk(j), cls_chunk(j), ...
                    tvec, CFG, ...
                    TBv_mat(:,j), TBh_mat(:,j), IA_mat(:,j), ...
                    Ts_mat(:,j), TC_mat(:,j), Tsoil1_mat(:,j), Tsoil2_mat(:,j), ...
                    SMref_mat(:,j), NDVI_mat(:,j), get_match_info_one(MATCH_INFO, j), ...
                    NDVI_v_max_chunk(j), NDVI_v_min_chunk(j), ...
                    ALBEDO_chunk(j), B_chunk(j), SF_mat(:,j), ...
                    CF_chunk(j), BD_chunk(j), H_chunk(j), ...
                    omega_fixed_pft, omega_fixed_pix, ...
                    freq_GHz, theta_default, TAU_REL_FRAC, KMIN, ...
                    ALPHA0, LAMBDA_ALPHA, BOUNDS_H, BOUNDS_ALPHA, ...
                    OMEGA0, BOUNDS_OMEGA, LAMBDA_SMOOTH, LAMBDA_TAU, ...
                    CFG.block_days, blkStarts, blkEnds, blkIndexCell, ...
                    wV, wH, opts_halpha, opts_om);
        end

    else

        for j = 1:Nc

            s_global = idx_chunk(j);

            [R_cell_chunk{j}, fail_flag_chunk(j), fail_msg_chunk(j)] = ...
                one_station_from_preloaded( ...
                    dq, s_global, ...
                    keys_chunk(j), network_chunk(j), station_chunk(j), ...
                    lat_chunk(j), lon_chunk(j), ...
                    iy_chunk(j), ix_chunk(j), cls_chunk(j), ...
                    tvec, CFG, ...
                    TBv_mat(:,j), TBh_mat(:,j), IA_mat(:,j), ...
                    Ts_mat(:,j), TC_mat(:,j), Tsoil1_mat(:,j), Tsoil2_mat(:,j), ...
                    SMref_mat(:,j), NDVI_mat(:,j), get_match_info_one(MATCH_INFO, j), ...
                    NDVI_v_max_chunk(j), NDVI_v_min_chunk(j), ...
                    ALBEDO_chunk(j), B_chunk(j), SF_mat(:,j), ...
                    CF_chunk(j), BD_chunk(j), H_chunk(j), ...
                    omega_fixed_pft, omega_fixed_pix, ...
                    freq_GHz, theta_default, TAU_REL_FRAC, KMIN, ...
                    ALPHA0, LAMBDA_ALPHA, BOUNDS_H, BOUNDS_ALPHA, ...
                    OMEGA0, BOUNDS_OMEGA, LAMBDA_SMOOTH, LAMBDA_TAU, ...
                    CFG.block_days, blkStarts, blkEnds, blkIndexCell, ...
                    wV, wH, opts_halpha, opts_om);
        end
    end

    %% -------- 当前 chunk 结果回填到总容器 --------
    R_cell(idx_chunk)    = R_cell_chunk;
    fail_flag(idx_chunk) = fail_flag_chunk;
    fail_msg(idx_chunk)  = fail_msg_chunk;

    fprintf('[CHUNK] %d / %d 完成 | 成功=%d | 失败=%d\n', ...
        ic, nChunk, nnz(~fail_flag_chunk & ~cellfun(@isempty,R_cell_chunk)), nnz(fail_flag_chunk));

    %% -------- 释放当前 chunk 的大矩阵 --------
    clear TBv_mat TBh_mat IA_mat Ts_mat TC_mat Tsoil1_mat Tsoil2_mat
    clear SMref_mat NDVI_mat SF_mat MATCH_INFO MATCH_chunk NDVI_DOY_CLIM_chunk
    clear R_cell_chunk fail_flag_chunk fail_msg_chunk
    clear network_chunk station_chunk lat_chunk lon_chunk keys_chunk grid_mesh_chunk
    clear iy_chunk ix_chunk cls_chunk grid_row_chunk lin_pix_chunk
    clear NDVI_v_max_chunk NDVI_v_min_chunk ALBEDO_chunk B_chunk CF_chunk BD_chunk H_chunk
end
%% ==================== 汇总保存（先保命） ====================
R = vertcat(R_cell{~cellfun(@isempty,R_cell)});
fail_list = keys_use(fail_flag);

% ===== 保存前删掉不想输出的 QC 字段（不影响 R_cell）=====
for i = 1:numel(R)
    if isfield(R(i),'inv_info') && isfield(R(i).inv_info,'QC') && ~isempty(R(i).inv_info.QC)
        R(i).inv_info.QC = qc_prune_for_output(R(i).inv_info.QC);
    end
end

out_all = fullfile(CFG.out_mat, sprintf('OMEGA_IDENT_%s.mat', CFG.shard_tag));
save(out_all, 'R', 'fail_list', 'fail_msg', 'use_idx', 'SHARD', 'CFG', '-v7.3');

fprintf('\n[ALL] shard汇总：%s\n', out_all);

%% ==================== ★按 ω-block 输出（后做，可失败） ====================
try
    save_block_grids_singlevar_fast(CFG, tvec, LC, R_cell, shard_tag, blkIndexCell, blkStarts, blkEnds);
catch ME
    fprintf(2,'[BLOCK][FAIL] %s\n', ME.message);
    fprintf(2,'[BLOCK][FAIL] 汇总文件已保存：%s\n', out_all);
end

%% ==================== Exp0 结束后生成 omega_pft / omega_pixel ====================
if string(CFG.EXP)=="Exp0"
    omega_pft = build_omega_pft_from_R(R);
    save(CFG.omega_pft_file, 'omega_pft');
    fprintf('[EXP0->PFT] 已生成 omega_pft_file: %s\n', CFG.omega_pft_file);

    [omega_pix_map, omega_pix_count] = build_omega_pixel_from_R(R, size(LC));
    save(CFG.omega_pix_file, 'omega_pix_map', 'omega_pix_count');
    fprintf('[EXP0->PIXEL] 已生成 omega_pix_file: %s\n', CFG.omega_pix_file);
end

fprintf('[TIME] 总耗时 %.1fs\n', toc(tAll));
end  % ===== 主函数结束 =====


%% =======================================================================
%% ====================== 站点反演（从预读矩阵取列） ======================
function [R_one, isFail, failMsg] = one_station_from_preloaded( ...
    dq, p, key, net, sta, lat0, lon0, ...
    iy, ix, cls, ...
    tvec, CFG, ...
    TBv_in, TBh_in, IA_in, Ts_in, TC_in, Tsoil1_in, Tsoil2_in, SM_ref, NDVI, MATCH_INFO, ...
   NDVI_max_ij, NDVI_min_ij, ALBEDO_ij, B_ij, SF_col, ...
    CF_ij, BD_ij, H_ij, ...
    omega_fixed_pft, omega_fixed_pix, ...
    freq_GHz, theta_default, TAU_REL_FRAC, KMIN, ...
    ALPHA0, LAMBDA_ALPHA, BOUNDS_H, BOUNDS_ALPHA, ...
    OMEGA0, BOUNDS_OMEGA, LAMBDA_SMOOTH, LAMBDA_TAU, ...
    block_days, blkStarts, blkEnds, blkIndexCell, ...
    wV, wH, opts_halpha, opts_om)

R_one   = [];
isFail  = false;
failMsg = "";

tag = worker_tag();
emit(dq, struct('type','start','p',p,'tag',tag,'key',key));

try
    Nt = numel(tvec);

    % ---------- TB/角度清洗 ----------
    TBv = TBv_in(:);
    TBh = TBh_in(:);
    IA  = IA_in(:);
    IA(~isfinite(IA)) = theta_default;

    spike_info = struct( ...
    'apply_to', "", ...
    'TBv_thr', nan, ...
    'TBh_thr', nan, ...
    'n_bad_v', 0, ...
    'n_bad_h', 0);

if should_apply_spike_cleaning(CFG)
    [thr_v, thr_h] = get_station_spike_thresholds(key, CFG);
    [TBv, bad_v] = remove_isolated_spikes(TBv, thr_v);
    [TBh, bad_h] = remove_isolated_spikes(TBh, thr_h);

    spike_info = struct( ...
        'apply_to', string(CFG.SPIKE.apply_to), ...
        'TBv_thr', thr_v, ...
        'TBh_thr', thr_h, ...
        'n_bad_v', nnz(bad_v), ...
        'n_bad_h', nnz(bad_h));
end

    Ts_use = nan(Nt,1);
    TC_use = nan(Nt,1);
    Tsoil1 = nan(Nt,1);
    Tsoil2 = nan(Nt,1);

    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
        Ts_use = Ts_in(:);
    else
        TC_use = TC_in(:);
        Tsoil1 = Tsoil1_in(:);
        Tsoil2 = Tsoil2_in(:);
    end

    % ---------- 固定 omega ----------
    omega_fixed = NaN;
    if any(strcmpi(char(CFG.EXP), {'Exp1a','Exp1b','Exp2'}))
        if upper(string(CFG.OMEGA_FIXED_MODE))=="PFT"
            omega_fixed = pick_omega_fixed_pft(omega_fixed_pft, cls);
        else
            omega_fixed = pick_omega_fixed_pixel(omega_fixed_pix, iy, ix);
        end
    end

% ---------- 反演核心 ----------
[OMEGA, SM_RET, VOD_RET, inv_info] = run_one_pixel_core_preloaded( ...
    p, dq, tag, iy, ix, ...
    tvec, CFG, cls, ...
    TBv, TBh, IA, Ts_use, TC_use, Tsoil1, Tsoil2, SM_ref(:), NDVI(:), MATCH_INFO, ...
   NDVI_max_ij, NDVI_min_ij, ALBEDO_ij, B_ij, SF_col, ...
    CF_ij, BD_ij, H_ij, ...
    omega_fixed, ...
    freq_GHz, TAU_REL_FRAC, KMIN, ...
    ALPHA0, LAMBDA_ALPHA, BOUNDS_H, BOUNDS_ALPHA, ...
    OMEGA0, BOUNDS_OMEGA, LAMBDA_SMOOTH, LAMBDA_TAU, ...
    block_days, blkStarts, blkEnds, blkIndexCell, ...
    wV, wH, opts_halpha, opts_om);

    station_info = struct( ...
    'network', net, ...
    'station', sta, ...
    'key', key, ...
    'latitude', lat0, ...
    'longitude', lon0);

R_one = struct( ...
    'station_info', station_info, ...
    'inv_info',     inv_info, ...
    'tvec',         tvec(:), ...
    'OMEGA',        OMEGA(:), ...
    'SM',           SM_RET(:), ...
    'VOD',          VOD_RET(:), ...
    'iy',           iy, ...
    'ix',           ix);

if string(CFG.EXP)=="Exp2"
    R_one.TBv_mod = inv_info.TBv_mod;
    R_one.TBh_mod = inv_info.TBh_mod;
    R_one.rV      = inv_info.rV;
    R_one.rH      = inv_info.rH;
end

    emit(dq, struct('type','done','p',p,'tag',tag,'msg','ok'));
catch ME
    isFail = true;
    failMsg = string(ME.identifier) + " | " + string(ME.message);
    emit(dq, struct('type','fail','p',p,'tag',tag,'msg',failMsg));
end
end


%% =======================================================================
%% ====================== 单像元反演核心（保留原输出） ====================
function [OMEGA, SM_RET, VOD_RET, inv_info] = run_one_pixel_core_preloaded( ...
    p, dq, tag, iy, ix, ...
    tvec, CFG, LCij, ...
    TBv, TBh, IA, Ts_use, TC_use, Tsoil1, Tsoil2, SM_ref, NDVI, MATCH_INFO, ...
    NDVI_max_ij, NDVI_min_ij, ALB_ij, b_ij, SF_col, ...
    CF_ij, BD_ij, H_ij, ...
    omega_fixed, ...
    freq_GHz, TAU_REL_FRAC, KMIN, ...
    ALPHA0, LAMBDA_ALPHA, BOUNDS_H, BOUNDS_ALPHA, ...
    OMEGA0, BOUNDS_OMEGA, LAMBDA_SMOOTH, LAMBDA_TAU, ...
    block_days, blkStarts, blkEnds, blkIndexCell, ...
    wV, wH, opts_halpha, opts_om)

Nt = numel(tvec);

OMEGA        = nan(Nt,1);
Tau_star     = nan(Nt,1);
SM_RET       = nan(Nt,1);
VOD_RET      = nan(Nt,1);
SM_FY_CH     = nan(Nt,1); %#ok<NASGU>
SM_FY_DH     = nan(Nt,1); %#ok<NASGU>
VOD_FY_CH    = nan(Nt,1); %#ok<NASGU>
VOD_FY_DH    = nan(Nt,1); %#ok<NASGU>
TBv_mod      = nan(Nt,1);
TBh_mod      = nan(Nt,1);
rV           = nan(Nt,1);
rH           = nan(Nt,1);

h_star_series = nan(Nt,1);
alpha_series  = nan(Nt,1);

Ct_series = nan(Nt,1);
TG_series = nan(Nt,1);

valid_tau = false(Nt,1);
low_tau   = false(Nt,1);

h_star     = NaN;
alpha_star = NaN;

diag = struct();

% ====================== Step 0: Tau ======================
for k = 1:Nt
    if isfinite(NDVI(k)) && isfinite(IA(k)) && isfinite(SF_col(k))
        Tau_star(k) = Tau( ...
            NDVI(k), NDVI_max_ij, NDVI_min_ij, LCij, b_ij, SF_col(k), IA(k), ...
            CFG.TAU_VWC2_MODE);
    end
end

% ====================== 温度方案组织 ======================
if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

    ok_base = isfinite(TBv) & isfinite(TBh) & isfinite(Ts_use) & isfinite(SM_ref) & isfinite(NDVI) & isfinite(IA);
    ok_base = ok_base(:);
else
    [Ct_series, TG_series] = build_effective_soil_temperature_scheme(SM_ref, Tsoil1, Tsoil2, CFG);
    ok_base = isfinite(TBv) & isfinite(TBh) & isfinite(TC_use) & isfinite(TG_series) & isfinite(SM_ref) & isfinite(NDVI) & isfinite(IA);
end

valid_tau = ok_base & isfinite(Tau_star);

if any(valid_tau)
    tau_min = min(Tau_star(valid_tau));
    tau_max = max(Tau_star(valid_tau));
    tau_thr = tau_min + TAU_REL_FRAC*(tau_max - tau_min);
else
    tau_thr = NaN;
end
low_tau = valid_tau & (Tau_star <= tau_thr);

n_low_tau = sum(low_tau);
n_use = sum(valid_tau);
if n_low_tau < KMIN
    error('低τ样本不足（%d < %d）', n_low_tau, KMIN);
end

% ====================== Step 1: h / alpha ======================
if upper(string(CFG.TB_SOURCE))=="SMAP" && upper(string(CFG.SMAP_HQ_MODE))=="YEARFILE_HQFIX"

    years_u = unique(year(tvec));
    for yy = years_u(:).'
        h_val = read_h_year_pixel(CFG, yy, iy, ix);
        idxy  = year(tvec)==yy;
        h_star_series(idxy) = h_val;
        alpha_series(idxy)  = CFG.Q_FIXED / max(h_val, eps);
    end

    h_star = median(h_star_series(valid_tau),'omitnan');
    alpha_star = median(alpha_series(valid_tau),'omitnan');

else

    % ===== Exp1a：直接读取 Exp0 的逐像元率定结果，不再重新反演 h/alpha =====
    if string(CFG.EXP)=="Exp1a"

        [h_star, alpha_star] = load_exp0_calib(CFG, iy, ix, LCij);

        h_star_series(valid_tau) = h_star;
        alpha_series(valid_tau)  = alpha_star;

    else

        % ===== 其余模式：仍然走原来的低τ反演 =====
        if string(CFG.EXP)=="Exp1b" && isfinite(omega_fixed)
            omega_low = omega_fixed;
        else
            omega_low = ALB_ij;
        end

        idx_use = find(low_tau);
        if numel(idx_use) < KMIN
            error('low_tau 样本不足。');
        end

        h0 = min(max(H_ij, BOUNDS_H(1)), BOUNDS_H(2));

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            fun_halpha = @(x) resid_halpha_single_temp( ...
                x, TBv(idx_use), TBh(idx_use), Ts_use(idx_use), Tau_star(idx_use), SM_ref(idx_use), IA(idx_use), ...
                CF_ij, freq_GHz, omega_low, ALPHA0, LAMBDA_ALPHA, wV, wH);
        else
            fun_halpha = @(x) resid_halpha_dual_temp( ...
                x, TBv(idx_use), TBh(idx_use), TC_use(idx_use), TG_series(idx_use), Tau_star(idx_use), SM_ref(idx_use), IA(idx_use), ...
                CF_ij, freq_GHz, omega_low, ALPHA0, LAMBDA_ALPHA, wV, wH);
        end

        xhat = lsqnonlin(fun_halpha, [h0;ALPHA0], ...
            [BOUNDS_H(1);BOUNDS_ALPHA(1)], [BOUNDS_H(2);BOUNDS_ALPHA(2)], opts_halpha);

        h_star     = xhat(1);
        alpha_star = xhat(2);

        h_star_series(valid_tau) = h_star;
        alpha_series(valid_tau)  = alpha_star;

        % ===== 只有 Exp0 才保存逐像元率定结果 =====
        if string(CFG.EXP)=="Exp0" && isfinite(h_star) && isfinite(alpha_star)
            save_exp0_calib(CFG, iy, ix, LCij, h_star, alpha_star);
        end

    end
end

if ~isfinite(h_star)
    h_star = median(h_star_series(valid_tau),'omitnan');
end
if ~isfinite(alpha_star)
    alpha_star = median(alpha_series(valid_tau),'omitnan');
end

% ====================== Step 2: 逐 block 反演 omega ======================
Kb = numel(blkIndexCell);

diag.n_use         = zeros(Kb,1,'uint16');
diag.algorithm     = strings(Kb,1);
diag.alg_code      = zeros(Kb,1,'uint8');
diag.damping       = nan(Kb,1);
diag.exitflag      = nan(Kb,1);
diag.iter          = zeros(Kb,1,'uint16');
diag.hit_max_iter  = false(Kb,1);
diag.final_cost    = nan(Kb,1);
diag.firstorderopt = nan(Kb,1);
diag.Tb_RMSE_V     = nan(Kb,1);
diag.Tb_RMSE_H     = nan(Kb,1);
diag.Tb_RMSE_HV    = nan(Kb,1);
diag.Jopt_norm2    = nan(Kb,1);
diag.Jtb_norm2     = nan(Kb,1);
diag.Jtb_rms       = nan(Kb,1);
diag.Jtb_maxabs    = nan(Kb,1);
diag.Jtb_minabs    = nan(Kb,1);

omega_prev = NaN;
prev_blkStart = NaT;

lambda_star_exp2 = NaN;
if string(CFG.EXP)=="Exp2"
    lambda_list = CFG.lambda_list(:);
    misfit = nan(numel(lambda_list),1);
    rough  = nan(numel(lambda_list),1);
    rmse   = nan(numel(lambda_list),1);

    % ===== 新增：保存每个 lambda 下的 block omega 时间序列 =====
    % 行 = 8天 block；列 = lambda
    % 例如 omega_by_lambda_block(:,1) 对应 lambda_list(1)
    omega_by_lambda_block = nan(Kb, numel(lambda_list));

    for ii = 1:numel(lambda_list)
        lam_now = lambda_list(ii);
        om_trial = nan(Kb,1);
        om_prev_trial = NaN;
        prev_trial = NaT;

        for bb = 1:Kb
            ib = blkIndexCell{bb};
            if isempty(ib), continue; end
            ib_use = ib(valid_tau(ib));
            if isempty(ib_use), continue; end

            if ~isnat(prev_trial)
                gapDays = days(blkStarts(bb)-prev_trial);
                if gapDays > block_days + 2
                    om_prev_trial = NaN;
                end
            end

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                fun_blk = @(om) resid_omega_block_single_temp( ...
                    om, TBv(ib_use), TBh(ib_use), Ts_use(ib_use), Tau_star(ib_use), SM_ref(ib_use), IA(ib_use), ...
                    CF_ij, freq_GHz, h_star_series(ib_use), alpha_series(ib_use), lam_now, om_prev_trial, wV, wH);
            else
                fun_blk = @(om) resid_omega_block_dual_temp( ...
                    om, TBv(ib_use), TBh(ib_use), TC_use(ib_use), TG_series(ib_use), Tau_star(ib_use), SM_ref(ib_use), IA(ib_use), ...
                    CF_ij, freq_GHz, h_star_series(ib_use), alpha_series(ib_use), lam_now, om_prev_trial, wV, wH);
            end

            om_init = iff(isfinite(om_prev_trial), om_prev_trial, OMEGA0);
            om_hat = lsqnonlin(fun_blk, om_init, BOUNDS_OMEGA(1), BOUNDS_OMEGA(2), opts_om);
            om_trial(bb) = om_hat;
            om_prev_trial = om_hat;
            prev_trial = blkStarts(bb);
        end

        % misfit
        rr = [];
for bb = 1:Kb
    ib = blkIndexCell{bb};
    if isempty(ib) || ~isfinite(om_trial(bb)), continue; end
    ib_use = ib(valid_tau(ib));
    if isempty(ib_use), continue; end

    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
        rr_blk = resid_omega_block_single_temp( ...
            om_trial(bb), TBv(ib_use), TBh(ib_use), Ts_use(ib_use), Tau_star(ib_use), SM_ref(ib_use), IA(ib_use), ...
            CF_ij, freq_GHz, h_star_series(ib_use), alpha_series(ib_use), 0, NaN, wV, wH);
    else
        rr_blk = resid_omega_block_dual_temp( ...
            om_trial(bb), TBv(ib_use), TBh(ib_use), TC_use(ib_use), TG_series(ib_use), Tau_star(ib_use), SM_ref(ib_use), IA(ib_use), ...
            CF_ij, freq_GHz, h_star_series(ib_use), alpha_series(ib_use), 0, NaN, wV, wH);
    end
    rr = [rr; rr_blk(:)]; %#ok<AGROW>
end

misfit(ii) = norm(rr);

if ~isempty(rr) && any(isfinite(rr))
    rmse(ii) = sqrt(mean(rr(isfinite(rr)).^2));
else
    rmse(ii) = NaN;
end

dOm = diff(om_trial(isfinite(om_trial)));
rough(ii) = norm(dOm);

% ===== 新增：保存当前 lambda 下的全年 block omega 序列 =====
omega_by_lambda_block(:, ii) = om_trial(:);

    end

    lambda_star_exp2 = pick_lcurve_corner(lambda_list, misfit, rough);
    if ~isfinite(lambda_star_exp2)
        lambda_star_exp2 = LAMBDA_SMOOTH;
    end
end

for bb = 1:Kb
    ib = blkIndexCell{bb};
    if isempty(ib), continue; end

    if ~isnat(prev_blkStart)
        gapDays = days(blkStarts(bb)-prev_blkStart);
        if gapDays > block_days + 2
            omega_prev = NaN;
        end
    end

    ib_use = ib(valid_tau(ib));
    diag.n_use(bb) = uint16(numel(ib_use));

    if isempty(ib_use)
        prev_blkStart = blkStarts(bb);
        continue;
    end

    % 固定 omega 实验
    isFixedExp = any(strcmpi(char(CFG.EXP), {'Exp1a','Exp1b'})) && isfinite(omega_fixed);

    if isFixedExp
        om_hat = omega_fixed;
        resnorm = NaN;
        exitflag = 9;
        output = struct('algorithm','FIXED','iterations',0,'firstorderopt',NaN,'lambda',NaN);
        J = [];
    else
        lamSmooth_use = LAMBDA_SMOOTH;
        if string(CFG.EXP)=="Exp2" && isfinite(lambda_star_exp2)
            lamSmooth_use = lambda_star_exp2;
        end

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            fun_blk = @(om) resid_omega_block_single_temp( ...
                om, TBv(ib_use), TBh(ib_use), Ts_use(ib_use), Tau_star(ib_use), SM_ref(ib_use), IA(ib_use), ...
                CF_ij, freq_GHz, h_star_series(ib_use), alpha_series(ib_use), lamSmooth_use, omega_prev, wV, wH);
        else
            fun_blk = @(om) resid_omega_block_dual_temp( ...
                om, TBv(ib_use), TBh(ib_use), TC_use(ib_use), TG_series(ib_use), Tau_star(ib_use), SM_ref(ib_use), IA(ib_use), ...
                CF_ij, freq_GHz, h_star_series(ib_use), alpha_series(ib_use), lamSmooth_use, omega_prev, wV, wH);
        end

        om_init = iff(isfinite(omega_prev), omega_prev, OMEGA0);
        [om_hat, resnorm, ~, exitflag, output, ~, J] = lsqnonlin( ...
            fun_blk, om_init, BOUNDS_OMEGA(1), BOUNDS_OMEGA(2), opts_om);
    end

    OMEGA(ib_use) = om_hat;
    omega_prev = om_hat;
    prev_blkStart = blkStarts(bb);

    % ===== 记录 diag =====
    diag.exitflag(bb) = exitflag;
    diag.final_cost(bb) = resnorm;

    fo = NaN;
    if isstruct(output) && isfield(output,'firstorderopt') && ~isempty(output.firstorderopt)
        try, fo = double(output.firstorderopt); catch, fo = NaN; end
    end
    diag.firstorderopt(bb) = fo;

    it = NaN;
    if isstruct(output) && isfield(output,'iterations')
        it = output.iterations;
    end
    if ~isfinite(it), it = 0; end
    diag.iter(bb) = uint16(max(0, floor(it)));
    diag.hit_max_iter(bb) = (double(diag.iter(bb)) >= double(opts_om.MaxIterations));

    algStr = "UNKNOWN";
    if isstruct(output) && isfield(output,'algorithm') && ~isempty(output.algorithm)
        algStr = string(output.algorithm);
    end
    diag.algorithm(bb) = algStr;
    diag.alg_code(bb) = alg_code_from_str(algStr);

    lam = NaN;
    if isstruct(output) && isfield(output,'lambda') && ~isempty(output.lambda)
        try, lam = double(output.lambda); catch, lam = NaN; end
    end
    diag.damping(bb) = lam;

    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
        [~, ~, rmV, rmH, rmHV] = tb_rmse_block_single_temp( ...
            om_hat, ib_use, TBv, TBh, Ts_use, Tau_star, SM_ref, IA, ...
            h_star_series, alpha_series, CF_ij, freq_GHz);
    else
        [~, ~, rmV, rmH, rmHV] = tb_rmse_block_dual_temp( ...
            om_hat, ib_use, TBv, TBh, TC_use, TG_series, Tau_star, SM_ref, IA, ...
            h_star_series, alpha_series, CF_ij, freq_GHz);
    end
    diag.Tb_RMSE_V(bb)  = rmV;
    diag.Tb_RMSE_H(bb)  = rmH;
    diag.Tb_RMSE_HV(bb) = rmHV;

    try
        if exist('J','var') && ~isempty(J)
            diag.Jopt_norm2(bb) = norm(J,2);
            mTb = 2*numel(ib_use);
            if size(J,1) >= mTb
                J_tb = J(1:mTb, :);
            else
                J_tb = J;
            end
            diag.Jtb_norm2(bb)  = norm(J_tb,2);
            diag.Jtb_rms(bb)    = sqrt(mean(J_tb(:).^2,'omitnan'));
            diag.Jtb_maxabs(bb) = max(abs(J_tb(:)));
            diag.Jtb_minabs(bb) = min(abs(J_tb(:)));
        end
    catch
    end

    emit(dq, struct('type','step2_prog','p',p,'tag',tag,'kk',bb,'K',Kb, ...
        'date', sprintf('%s~%s', datestr(blkStarts(bb),'yyyy-mm-dd'), datestr(blkEnds(bb),'yyyy-mm-dd'))));
end

% ====================== QC 计算（输出结构保持不变） ======================
if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    Ts_qc = Ts_use;
else
    Ts_qc = TG_series;
    bad = ~isfinite(Ts_qc);
    Ts_qc(bad) = TC_use(bad);
end

qc_info = qc_compute_blocks_optionA(CFG, blkStarts, blkEnds, blkIndexCell, valid_tau, ...
    TBv, TBh, Ts_qc, Tau_star, SM_ref, IA, ...
    h_star_series, alpha_series, OMEGA, CF_ij, freq_GHz, wV, wH, BOUNDS_OMEGA, diag, ...
    CFG.TEMP_SCHEME, TC_use, TG_series, Ts_use);

% ---------- 回带 DDCA ----------
porosity = 1 - BD_ij/2.65;
for k = 1:Nt
    if ~valid_tau(k), continue; end
    if ~isfinite(OMEGA(k)), continue; end

    hk = pick_one(h_star_series, k);
    ak = pick_one(alpha_series,  k);

    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
        [SM_RET(k), VOD_RET(k)] = DDCA_single_temp( ...
            TBv(k), TBh(k), Ts_use(k), Tau_star(k), hk, CF_ij, OMEGA(k), porosity, freq_GHz, IA(k), ak, LAMBDA_TAU);

        [TBv_mod(k), TBh_mod(k)] = tb_forward_single_temp( ...
            SM_RET(k), VOD_RET(k), hk, ak, OMEGA(k), Ts_use(k), IA(k), CF_ij, freq_GHz, 1.0);
    else
        [SM_RET(k), VOD_RET(k)] = DDCA_dual_temp( ...
            TBv(k), TBh(k), TC_use(k), TG_series(k), Tau_star(k), hk, CF_ij, OMEGA(k), porosity, freq_GHz, IA(k), ak, LAMBDA_TAU);

        [TBv_mod(k), TBh_mod(k)] = tb_forward_dual_temp( ...
            SM_RET(k), VOD_RET(k), hk, ak, OMEGA(k), TC_use(k), TG_series(k), IA(k), CF_ij, freq_GHz, 1.0);
    end

    rV(k) = TBv(k) - TBv_mod(k);
    rH(k) = TBh(k) - TBh_mod(k);
end

% ---------- 输出 ----------
inv_info = struct();
inv_info.iy = iy;
inv_info.ix = ix;
inv_info.class_id = LCij;
inv_info.h_star = h_star;
inv_info.alpha_star = alpha_star;
inv_info.block_days = block_days;
inv_info.LAMBDA_SMOOTH = LAMBDA_SMOOTH;
inv_info.n_low_tau = n_low_tau;
inv_info.n_use     = n_use;
inv_info.t_step1   = NaN;
inv_info.t_step2   = NaN;
inv_info.EXP       = CFG.EXP;
inv_info.WEIGHT_MODE = CFG.WEIGHT_MODE;

exp2_info = struct( ...
    'lambda_list', [], ...
    'misfit',      [], ...
    'roughness',   [], ...
    'rmse',        [], ...
    'lambda_star', NaN, ...
    'omega_by_lambda_block', [], ...
    'block_start', [], ...
    'block_end', []);

if string(CFG.EXP)=="Exp2"
    exp2_info.lambda_list = lambda_list(:);
    exp2_info.misfit      = misfit(:);
    exp2_info.roughness   = rough(:);
    exp2_info.rmse        = rmse(:);
    exp2_info.lambda_star = lambda_star_exp2;

    % ===== 新增：用于图3d，多 lambda 下的 omega 时间序列 =====
    exp2_info.omega_by_lambda_block = omega_by_lambda_block;
    exp2_info.block_start = blkStarts(:);
    exp2_info.block_end   = blkEnds(:);
end
inv_info.exp2 = exp2_info;

inv_info.TB_SOURCE = string(CFG.TB_SOURCE);
inv_info.SM_SOURCE = string(CFG.SM_SOURCE);
inv_info.RUN_DOMAIN = string(CFG.RUN_DOMAIN);

inv_info.OMEGA_FIXED_MODE = string(CFG.OMEGA_FIXED_MODE);
inv_info.omega_fixed_used = omega_fixed;

if upper(string(CFG.TB_SOURCE))=="SMAP"
    inv_info.SMAP_HQ_MODE = string(CFG.SMAP_HQ_MODE);
    inv_info.Q_FIXED = CFG.Q_FIXED;
end

if upper(string(CFG.TB_SOURCE))=="FY"
    inv_info.FY_PLATFORM = string(CFG.FY_PLATFORM);
    inv_info.MATCH_ENABLE = CFG.MATCH_ENABLE;
    inv_info.MATCH_METHOD = string(CFG.MATCH_METHOD);
end

inv_info.QC = qc_info;

if string(CFG.EXP)=="Exp2"
    inv_info.TBv_mod = TBv_mod;
    inv_info.TBh_mod = TBh_mod;
    inv_info.rV      = rV;
    inv_info.rH      = rH;
end

emit(dq, struct('type','step2_done','p',p,'tag',tag,'msg','omega_done'));
end


%% =======================================================================
%% ============================ 预读总函数 =================================
function [TBv_mat, TBh_mat, IA_mat, Ts_mat, TC_mat, Tsoil1_mat, Tsoil2_mat, SMref_mat, NDVI_mat, SF_mat, MATCH_INFO] = ...
    preload_timeseries_merged(tvec, CFG, lin_pix, iy_list, ix_list, cls_list, lon_use, ...
    NDVI_clim_max, NDVI_clim_min, SF_static, ...
    GLDAS_INDEX, GLDAS_TEMPLATE, GLDAS_DAY_SLOT, t_grid, grid, grid_row_list, MATCH, NDVI_DOY_CLIM)

Nt = numel(tvec);
Np = numel(lin_pix);

TBv_mat    = nan(Nt,Np);
TBh_mat    = nan(Nt,Np);
IA_mat     = nan(Nt,Np);
Ts_mat     = nan(Nt,Np);
TC_mat     = nan(Nt,Np);
Tsoil1_mat = nan(Nt,Np);
Tsoil2_mat = nan(Nt,Np);
SMref_mat  = nan(Nt,Np);
NDVI_mat   = nan(Nt,Np);
SF_mat     = nan(Nt,Np);

if isfield(CFG,'SAVE_MATCH_INFO') && CFG.SAVE_MATCH_INFO
    MATCH_INFO = cell(Np,1);
    for s = 1:Np
        MATCH_INFO{s} = struct('target_utc',NaT(Nt,1), 'picked_utc',NaT(Nt,1), 'picked_file',strings(Nt,1));
    end
else
    MATCH_INFO = [];
end

if ~isempty(t_grid) && isdatetime(t_grid)
    [~, col_ismn] = ismember(dateshift(tvec,'start','day'), dateshift(t_grid,'start','day'));
else
    col_ismn = zeros(numel(tvec),1);
end

if upper(string(CFG.TEMP_SCHEME))=="DUAL" && isfield(CFG,'USE_GLDAS_TEMPLATE') && CFG.USE_GLDAS_TEMPLATE
    slot_idx_all   = nan(Np,1);
    day_offset_all = nan(Np,1);

    for s = 1:Np
        iy = iy_list(s);
        ix = ix_list(s);
        slot_idx_all(s)   = double(GLDAS_TEMPLATE.slot_index(iy,ix));
        day_offset_all(s) = double(GLDAS_TEMPLATE.slot_day_offset(iy,ix));
    end

    m_prev = isfinite(slot_idx_all) & (day_offset_all == -1);
    m_curr = isfinite(slot_idx_all) & (day_offset_all == 0);
    m_next = isfinite(slot_idx_all) & (day_offset_all == 1);

    pix_prev  = find(m_prev);
    pix_curr  = find(m_curr);
    pix_next  = find(m_next);

    slot_prev = slot_idx_all(pix_prev);
    slot_curr = slot_idx_all(pix_curr);
    slot_next = slot_idx_all(pix_next);
else
    slot_idx_all   = [];
    day_offset_all = [];

    pix_prev  = [];
    pix_curr  = [];
    pix_next  = [];

    slot_prev = [];
    slot_curr = [];
    slot_next = [];
end

if upper(string(CFG.TEMP_SCHEME))=="DUAL" && isfield(CFG,'USE_GLDAS_TEMPLATE') && CFG.USE_GLDAS_TEMPLATE
    row_prev_all = nan(Nt,1);
    row_curr_all = nan(Nt,1);
    row_next_all = nan(Nt,1);

    day_tab = GLDAS_DAY_SLOT.days;

    for k = 1:Nt
        d0 = dateshift(tvec(k),'start','day');
        id_prev = find(day_tab == d0 - days(1), 1, 'first');
        id_curr = find(day_tab == d0,           1, 'first');
        id_next = find(day_tab == d0 + days(1), 1, 'first');

        if ~isempty(id_prev), row_prev_all(k) = id_prev; end
        if ~isempty(id_curr), row_curr_all(k) = id_curr; end
        if ~isempty(id_next), row_next_all(k) = id_next; end
    end
else
    row_prev_all = [];
    row_curr_all = [];
    row_next_all = [];
end

for k = 1:Nt
    if mod(k, max(1, getf(CFG,'PRINT_EVERY_DAYS',20)))==1 || k==Nt
        fprintf('[PRELOAD] %d / %d : %s\n', k, Nt, datestr(tvec(k),'yyyy-mm-dd'));
    end

    name = datestr(tvec(k),'yyyymmdd');

    if upper(string(CFG.TB_SOURCE))=="FY"
        if upper(string(CFG.FY_PLATFORM))=="3D"
            f_tb = fullfile(CFG.fy3d_folder,[name,'.mat']);
        elseif upper(string(CFG.FY_PLATFORM))=="3B"
            f_tb = fullfile(CFG.fy3b_folder,[name,'.mat']);
        else
            error('未知 CFG.FY_PLATFORM=%s', string(CFG.FY_PLATFORM));
        end
    else
        f_tb = fullfile(CFG.smap_folder,[name,'.mat']);
    end

    f_sp   = fullfile(CFG.smap_folder,[name,'.mat']);
    f_ndvi = fullfile(CFG.ndvi_folder,[name,'.mat']);

    % 任何关键文件缺失：当天直接跳过，不报错
    if exist(f_tb,'file')~=2
        fprintf('[MISS][TB  ] %s\n', f_tb);
        continue;
    end
    if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"
    if exist(f_ndvi,'file')~=2
        fprintf('[MISS][NDVI] %s\n', f_ndvi);
        continue;
    end
end
    need_smap_file = false;
if upper(string(CFG.SM_SOURCE))=="SMAP"
    need_smap_file = true;
end
if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    need_smap_file = true;
end
if upper(string(CFG.SF_MODE))=="INVERTED_DAILY"
    need_smap_file = true;
end

if need_smap_file
    if exist(f_sp,'file')~=2
        fprintf('[MISS][SMAP] %s\n', f_sp);
        continue;
    end
end
    if upper(string(CFG.SM_SOURCE))=="DDCA"
        f_ddca = fullfile(CFG.ddca_sm_folder,[name,'.mat']);
        if exist(f_ddca,'file')~=2
            fprintf('[MISS][DDCA] %s\n', f_ddca);
            continue;
        end
    end

    % ===== TB / IA =====
    if upper(string(CFG.TB_SOURCE))=="FY"
        Sfy = load(f_tb, 'TBv','TBh','IA');

        if k == 1
            fprintf('\n[DEBUG-FY] platform=%s file=%s\n', char(string(CFG.FY_PLATFORM)), f_tb);
            fprintf('[DEBUG-FY] Np=%d, size(lin_pix)=%s, min(lin_pix)=%g, max(lin_pix)=%g\n', ...
                Np, mat2str(size(lin_pix)), min(lin_pix), max(lin_pix));
            fprintf('[DEBUG-FY] has TBv=%d TBh=%d IA=%d\n', isfield(Sfy,'TBv'), isfield(Sfy,'TBh'), isfield(Sfy,'IA'));
            if isfield(Sfy,'TBv')
                fprintf('[DEBUG-FY] size(TBv)=%s class=%s numel=%d\n', ...
                    mat2str(size(Sfy.TBv)), class(Sfy.TBv), numel(Sfy.TBv));
            end
            if isfield(Sfy,'TBh')
                fprintf('[DEBUG-FY] size(TBh)=%s class=%s numel=%d\n', ...
                    mat2str(size(Sfy.TBh)), class(Sfy.TBh), numel(Sfy.TBh));
            end
            if isfield(Sfy,'IA')
                fprintf('[DEBUG-FY] size(IA)=%s class=%s numel=%d\n', ...
                    mat2str(size(Sfy.IA)), class(Sfy.IA), numel(Sfy.IA));
            end
        end

        TBv_row = nan(1,Np);
        TBh_row = nan(1,Np);
        IA_row  = nan(1,Np);

        if isfield(Sfy,'TBv')
            assert(max(lin_pix) <= numel(Sfy.TBv), ...
                'TBv越界: max(lin_pix)=%g, numel(TBv)=%d', max(lin_pix), numel(Sfy.TBv));
            TBv_row = double(Sfy.TBv(lin_pix));
        end

        if isfield(Sfy,'TBh')
            assert(max(lin_pix) <= numel(Sfy.TBh), ...
                'TBh越界: max(lin_pix)=%g, numel(TBh)=%d', max(lin_pix), numel(Sfy.TBh));
            TBh_row = double(Sfy.TBh(lin_pix));
        end

        if isfield(Sfy,'IA')
            assert(max(lin_pix) <= numel(Sfy.IA), ...
                'IA越界: max(lin_pix)=%g, numel(IA)=%d', max(lin_pix), numel(Sfy.IA));
            tmp = Sfy.IA(lin_pix);
            IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
        end

        if k == 1
            fprintf('[DEBUG-FY] size(TBv_row)=%s class=%s finite=%d\n', ...
                mat2str(size(TBv_row)), class(TBv_row), nnz(isfinite(TBv_row)));
            fprintf('[DEBUG-FY] size(TBh_row)=%s class=%s finite=%d\n', ...
                mat2str(size(TBh_row)), class(TBh_row), nnz(isfinite(TBh_row)));
            fprintf('[DEBUG-FY] size(IA_row)=%s class=%s finite=%d\n', ...
                mat2str(size(IA_row)), class(IA_row), nnz(isfinite(IA_row)));
        end

        % ===== 只有 FY3B 才做 3B->3D 匹配校正 =====
        if upper(string(CFG.FY_PLATFORM))=="3B" && isfield(CFG,'MATCH_ENABLE') && CFG.MATCH_ENABLE ...
                && ~isempty(MATCH) && upper(string(CFG.MATCH_METHOD))~="NONE"
            if k == 1
                fprintf('[DEBUG-FY] apply_match_row on 3B first day\n');
            end
            TBv_row = apply_match_row(TBv_row, MATCH.V, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
            TBh_row = apply_match_row(TBh_row, MATCH.H, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
        end

        TBv_mat(k,:) = TBv_row;
        TBh_mat(k,:) = TBh_row;
        IA_mat(k,:)  = IA_row;

    else
        Ssp = load(f_tb, 'TBv','TBh','IA');

        if isfield(Ssp,'TBv'), TBv_mat(k,:) = Ssp.TBv(lin_pix); end
        if isfield(Ssp,'TBh'), TBh_mat(k,:) = Ssp.TBh(lin_pix); end

        IA_row = nan(1,Np);
        if isfield(Ssp,'IA')
            tmp = Ssp.IA(lin_pix);
            IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
        end
        IA_mat(k,:) = IA_row;
    end

    % ===== SMref =====
    sm_src = upper(string(CFG.SM_SOURCE));
    if sm_src=="SMAP"
        Ssm = load(f_sp, 'sm_dca');
        if isfield(Ssm,'sm_dca')
            SMref_mat(k,:) = Ssm.sm_dca(lin_pix);
        end
    elseif sm_src=="DDCA"
        Sdd = load(f_ddca, 'SM');
        if isfield(Sdd,'SM')
            SMref_mat(k,:) = Sdd.SM(lin_pix);
        end
    else
        c = col_ismn(k);
        if c>0
            SMref_mat(k,:) = grid(grid_row_list(:), c).';
        end
    end
    SMref_mat(k, SMref_mat(k,:)<-0.01 | SMref_mat(k,:)>1.0) = NaN;

    % ===== NDVI =====
    % ===== NDVI（只用于后续 Tau/反演；不影响 SF 反推）=====
if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"

    Svi = load(f_ndvi, 'NDVI');
    if isfield(Svi,'NDVI')
        NDVI_mat(k,:) = double(Svi.NDVI(lin_pix));
    end
elseif upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    doy_k = day(tvec(k),'dayofyear');

    if ~isempty(NDVI_DOY_CLIM)
        if size(NDVI_DOY_CLIM,1) ~= 366 || size(NDVI_DOY_CLIM,2) ~= Np
            error('NDVI_DOY_CLIM 尺寸不匹配：期望 [366 x %d]，实际 [%d x %d]', ...
                Np, size(NDVI_DOY_CLIM,1), size(NDVI_DOY_CLIM,2));
        end
        NDVI_mat(k,:) = NDVI_DOY_CLIM(doy_k,:);
    end

else
    error('未知 CFG.NDVI_MODE=%s', string(CFG.NDVI_MODE));
end

    % ===== SF（静态 or 倒推daily）=====
if upper(string(CFG.SF_MODE))=="STATIC"

    SF_mat(k,:) = SF_static(lin_pix);

elseif upper(string(CFG.SF_MODE))=="INVERTED_DAILY"

    % 1) 读当天 DOY 对应的静态 NDVI_clim
    doy_k = day(tvec(k),'dayofyear');
    f_clim = fullfile(CFG.ndvi_clim_folder, sprintf('%d.mat', doy_k));
    if exist(f_clim,'file')~=2
        error('缺少 NDVI_clim 文件：%s', f_clim);
    end

    Sclim = load(f_clim, CFG.ndvi_clim_varname);
    NDVI_clim_grid = Sclim.(CFG.ndvi_clim_varname);
    NDVI_clim_row  = double(NDVI_clim_grid(lin_pix));

    % 2) 读当天 SMAP 文件里的 vwc
    Svwc = load(f_sp, 'vwc');
    if ~isfield(Svwc, 'vwc')
        error('SMAP 日文件缺少变量 vwc：%s', f_sp);
    end
    vwc_row = double(Svwc.vwc(lin_pix));

    % 3) 构造当天 sf_row
SF_mat(k,:) = build_sf_row_daily( ...
    vwc_row, ...
    NDVI_clim_row, ...
    NDVI_clim_max(lin_pix), ...
    NDVI_clim_min(lin_pix), ...
    cls_list(:).', ...
    CFG.SF_INVERT_MODE);

else
    error('未知 CFG.SF_MODE=%s', string(CFG.SF_MODE));
end


    % ===== 调试输出：检查当天是否读对 =====
    if k <= 5 || mod(k,30)==0 || k==Nt
        nTBv   = nnz(isfinite(TBv_mat(k,:)));
        nTBh   = nnz(isfinite(TBh_mat(k,:)));
        nIA    = nnz(isfinite(IA_mat(k,:)));
        nNDVI  = nnz(isfinite(NDVI_mat(k,:)));
        nSMref = nnz(isfinite(SMref_mat(k,:)));

        tb_tag = string(CFG.TB_SOURCE);
        if upper(string(CFG.TB_SOURCE))=="FY"
            tb_tag = "FY-" + upper(string(CFG.FY_PLATFORM));
        end

        fprintf('[CHK ] %s | TB=%s | nTBv=%d nTBh=%d nIA=%d nNDVI=%d nSM=%d\n', ...
            datestr(tvec(k),'yyyy-mm-dd'), char(tb_tag), ...
            nTBv, nTBh, nIA, nNDVI, nSMref);
    end

    % ===== 温度读取 =====
    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

        % ===== 原单温度：直接从原文件读 Ts，不做 GLDAS 匹配 =====
        Ssp = load(f_sp, 'Ts');
        if isfield(Ssp,'Ts') && ~isempty(Ssp.Ts)
            Ts_mat(k,:) = Ssp.Ts(lin_pix);
        else
            Ts_mat(k,:) = NaN;
        end

    else

        % ===== 双温度：优先用模板；否则走原始逐日匹配 =====
        if isfield(CFG,'USE_GLDAS_TEMPLATE') && CFG.USE_GLDAS_TEMPLATE

            gidx_all = nan(Np,1);

            if isfinite(row_prev_all(k))
                idx_prev = GLDAS_DAY_SLOT.gidx_mat(row_prev_all(k), :);
                okp = slot_prev>=1 & slot_prev<=numel(idx_prev);
                gidx_all(pix_prev(okp)) = idx_prev(slot_prev(okp));
            end

            if isfinite(row_curr_all(k))
                idx_curr = GLDAS_DAY_SLOT.gidx_mat(row_curr_all(k), :);
                okc = slot_curr>=1 & slot_curr<=numel(idx_curr);
                gidx_all(pix_curr(okc)) = idx_curr(slot_curr(okc));
            end

            if isfinite(row_next_all(k))
                idx_next = GLDAS_DAY_SLOT.gidx_mat(row_next_all(k), :);
                okn = slot_next>=1 & slot_next<=numel(idx_next);
                gidx_all(pix_next(okn)) = idx_next(slot_next(okn));
            end

            uidx = unique(gidx_all(isfinite(gidx_all)));

            for uu = 1:numel(uidx)
                ig = uidx(uu);
                ss = find(gidx_all == ig);

                G = load(fullfile(CFG.gldas_mat_folder, GLDAS_INDEX.files(ig).name), ...
                    CFG.gldas_var_TC, CFG.gldas_var_Tsoil1, CFG.gldas_var_Tsoil2);

                TC_grid     = G.(CFG.gldas_var_TC);
                Tsoil1_grid = G.(CFG.gldas_var_Tsoil1);
                Tsoil2_grid = G.(CFG.gldas_var_Tsoil2);

                TC_mat(k,ss)     = TC_grid(lin_pix(ss));
                Tsoil1_mat(k,ss) = Tsoil1_grid(lin_pix(ss));
                Tsoil2_mat(k,ss) = Tsoil2_grid(lin_pix(ss));

                if iscell(MATCH_INFO)
                    t_pick = GLDAS_INDEX.t_utc(ig);
                    picked_name = string(GLDAS_INDEX.files(ig).name);
                    for jj = 1:numel(ss)
                        s = ss(jj);
                        MATCH_INFO{s}.picked_utc(k)  = t_pick;
                        MATCH_INFO{s}.picked_file(k) = picked_name;
                    end
                end
            end

            if k <= 5 || mod(k,30)==0 || k==Nt
                nTC = nnz(isfinite(TC_mat(k,:)));
                nT1 = nnz(isfinite(Tsoil1_mat(k,:)));
                nT2 = nnz(isfinite(Tsoil2_mat(k,:)));

                fprintf('[TEMP] %s | nTC=%d nTsoil1=%d nTsoil2=%d\n', ...
                    datestr(tvec(k),'yyyy-mm-dd'), nTC, nT1, nT2);
            end

        else

            if upper(string(CFG.TB_SOURCE))=="FY"
                if upper(string(CFG.FY_PLATFORM))=="3D"
                    local_hour_now = CFG.fy3d_desc_local_hour;
                elseif upper(string(CFG.FY_PLATFORM))=="3B"
                    local_hour_now = CFG.fy3b_desc_local_hour;
                else
                    error('未知 CFG.FY_PLATFORM=%s', string(CFG.FY_PLATFORM));
                end
                target_utc = local_overpass_to_utc_vec(tvec(k), lon_use(:), local_hour_now);
            else
                target_utc = local_overpass_to_utc_vec(tvec(k), lon_use(:), CFG.smap_desc_local_hour);
            end

            idx_pick = pick_gldas_file_indices(GLDAS_INDEX.t_utc, target_utc, CFG.gldas_time_tol_hours);
            uidx = unique(idx_pick(isfinite(idx_pick)));

            for uu = 1:numel(uidx)
                ig = uidx(uu);
                ss = find(idx_pick == ig);

                G = load(fullfile(CFG.gldas_mat_folder, GLDAS_INDEX.files(ig).name), ...
                    CFG.gldas_var_TC, CFG.gldas_var_Tsoil1, CFG.gldas_var_Tsoil2);

                TC_grid     = G.(CFG.gldas_var_TC);
                Tsoil1_grid = G.(CFG.gldas_var_Tsoil1);
                Tsoil2_grid = G.(CFG.gldas_var_Tsoil2);

                TC_mat(k,ss)     = TC_grid(lin_pix(ss));
                Tsoil1_mat(k,ss) = Tsoil1_grid(lin_pix(ss));
                Tsoil2_mat(k,ss) = Tsoil2_grid(lin_pix(ss));

                if iscell(MATCH_INFO)
                    for jj = 1:numel(ss)
                        s = ss(jj);
                        MATCH_INFO{s}.target_utc(k)  = target_utc(s);
                        MATCH_INFO{s}.picked_utc(k)  = GLDAS_INDEX.t_utc(ig);
                        MATCH_INFO{s}.picked_file(k) = string(GLDAS_INDEX.files(ig).name);
                    end
                end
            end

        end
    end
end
end

%% =======================================================================
%% ============================== block保存 ================================
function save_block_grids_singlevar_fast(CFG, tvec, LC, R_cell, shard_tag, blkIndexCell, blkStarts, blkEnds)

nrow = size(LC,1);
ncol = size(LC,2);
Kb   = numel(blkIndexCell);

useSingle = isfield(CFG,'DAILY_USE_SINGLE') && CFG.DAILY_USE_SINGLE;

for bb = 1:Kb
    ib = blkIndexCell{bb};
    if isempty(ib), continue; end

    if useSingle
    OMEGA_grid = nan(nrow,ncol,'single');
    else
        OMEGA_grid = nan(nrow,ncol);
    end

    % block级 QC grid（结构保持）
    QC = struct();
    QC.n_use        = nan(nrow,ncol);
    QC.algorithm    = strings(nrow,ncol);
    QC.alg_code     = nan(nrow,ncol);
    QC.damping      = nan(nrow,ncol);
    QC.exitflag     = nan(nrow,ncol);
    QC.iter         = nan(nrow,ncol);
    QC.hit_max_iter = false(nrow,ncol);
    QC.final_cost   = nan(nrow,ncol);
    QC.firstorderopt= nan(nrow,ncol);
    QC.Tb_RMSE_V    = nan(nrow,ncol);
    QC.Tb_RMSE_H    = nan(nrow,ncol);
    QC.Tb_RMSE_HV   = nan(nrow,ncol);
    QC.Jopt_norm2   = nan(nrow,ncol);
    QC.Jtb_norm2    = nan(nrow,ncol);
    QC.Jtb_rms      = nan(nrow,ncol);
    QC.Jtb_maxabs   = nan(nrow,ncol);
    QC.Jtb_minabs   = nan(nrow,ncol);
    QC.condJ        = nan(nrow,ncol);
    QC.condK        = nan(nrow,ncol);
    QC.smin         = nan(nrow,ncol);
    QC.sratio       = nan(nrow,ncol);
    QC.flag         = nan(nrow,ncol);

    for ii = 1:numel(R_cell)
        Ri = R_cell{ii};
        if isempty(Ri), continue; end
        if ~isfield(Ri,'iy') || ~isfield(Ri,'ix') || ~isfield(Ri,'OMEGA'), continue; end

        iy = Ri.iy;
        ix = Ri.ix;

        vals = Ri.OMEGA(ib);
        vals = vals(isfinite(vals));
        if ~isempty(vals)
            vmed = median(vals,'omitnan');
            if useSingle
                OMEGA_grid(iy,ix) = single(vmed);
            else
                OMEGA_grid(iy,ix) = vmed;
            end
        end

        if isfield(Ri,'inv_info') && isfield(Ri.inv_info,'QC') && ~isempty(Ri.inv_info.QC)
            q = Ri.inv_info.QC;
            if bb <= numel(q.n_use),         QC.n_use(iy,ix)        = double(q.n_use(bb)); end
            if bb <= numel(q.algorithm),     QC.algorithm(iy,ix)    = string(q.algorithm(bb)); end
            if bb <= numel(q.alg_code),      QC.alg_code(iy,ix)     = double(q.alg_code(bb)); end
            if bb <= numel(q.damping),       QC.damping(iy,ix)      = q.damping(bb); end
            if bb <= numel(q.exitflag),      QC.exitflag(iy,ix)     = q.exitflag(bb); end
            if bb <= numel(q.iter),          QC.iter(iy,ix)         = double(q.iter(bb)); end
            if bb <= numel(q.hit_max_iter),  QC.hit_max_iter(iy,ix) = q.hit_max_iter(bb); end
            if bb <= numel(q.final_cost),    QC.final_cost(iy,ix)   = q.final_cost(bb); end
            if bb <= numel(q.firstorderopt), QC.firstorderopt(iy,ix)= q.firstorderopt(bb); end
            if bb <= numel(q.Tb_RMSE_V),     QC.Tb_RMSE_V(iy,ix)    = q.Tb_RMSE_V(bb); end
            if bb <= numel(q.Tb_RMSE_H),     QC.Tb_RMSE_H(iy,ix)    = q.Tb_RMSE_H(bb); end
            if bb <= numel(q.Tb_RMSE_HV),    QC.Tb_RMSE_HV(iy,ix)   = q.Tb_RMSE_HV(bb); end
            if bb <= numel(q.Jopt_norm2),    QC.Jopt_norm2(iy,ix)   = q.Jopt_norm2(bb); end
            if bb <= numel(q.Jtb_norm2),     QC.Jtb_norm2(iy,ix)    = q.Jtb_norm2(bb); end
            if bb <= numel(q.Jtb_rms),       QC.Jtb_rms(iy,ix)      = q.Jtb_rms(bb); end
            if bb <= numel(q.Jtb_maxabs),    QC.Jtb_maxabs(iy,ix)   = q.Jtb_maxabs(bb); end
            if bb <= numel(q.Jtb_minabs),    QC.Jtb_minabs(iy,ix)   = q.Jtb_minabs(bb); end
            if bb <= numel(q.condJ),         QC.condJ(iy,ix)        = q.condJ(bb); end
            if bb <= numel(q.condK),         QC.condK(iy,ix)        = q.condK(bb); end
            if bb <= numel(q.smin),          QC.smin(iy,ix)         = q.smin(bb); end
            if bb <= numel(q.sratio),        QC.sratio(iy,ix)       = q.sratio(bb); end
            if bb <= numel(q.flag),          QC.flag(iy,ix)         = q.flag(bb); end
        end
    end

    % ===== 改成标准8天窗口 =====
    ymd1 = datestr(blkStarts(bb),'yyyymmdd');
ymd2 = datestr(blkEnds(bb),'yyyymmdd');

date_start = ymd1;
date_end   = ymd2;
date_range_str = sprintf('%s~%s', ymd1, ymd2);

out_file = fullfile(CFG.out_block, sprintf('%s_%s_%s.mat', ymd1, ymd2, shard_tag));
QC = qc_prune_for_output(QC);
save(out_file, 'OMEGA_grid', 'QC', 'date_start', 'date_end', 'date_range_str', '-v7.3');
end
end


%% =======================================================================
%% ======================== Exp0后处理：PFT均值 ============================
function omega_pft = build_omega_pft_from_R(R)
omega_pft = nan(17,1);
for pft = 0:16
    vals = [];
    for i = 1:numel(R)
        if ~isfield(R(i),'inv_info') || ~isfield(R(i).inv_info,'class_id'), continue; end
        if double(R(i).inv_info.class_id) ~= pft, continue; end
        if ~isfield(R(i),'OMEGA'), continue; end
        om = R(i).OMEGA(:);
        vals = [vals; om(isfinite(om))]; %#ok<AGROW>
    end
    if ~isempty(vals)
        omega_pft(pft+1) = median(vals,'omitnan');
    end
end
end

function save_exp0_calib(CFG, iy, ix, LCij, h_star, alpha_star)
if ~exist(CFG.exp0_calib_dir,'dir')
    mkdir(CFG.exp0_calib_dir);
end

f = fullfile(CFG.exp0_calib_dir, sprintf('exp0_calib_pix_%d_%d.mat', iy, ix));
PFT = LCij;
save(f, 'iy', 'ix', 'PFT', 'h_star', 'alpha_star');
end
function [omega_pix_map, omega_pix_count] = build_omega_pixel_from_R(R, szLC)
omega_pix_map   = nan(szLC);
omega_pix_count = zeros(szLC);

M = containers.Map('KeyType','uint32','ValueType','any');
for i = 1:numel(R)
    if ~isfield(R(i),'inv_info'), continue; end
    if ~isfield(R(i).inv_info,'iy') || ~isfield(R(i).inv_info,'ix'), continue; end
    if ~isfield(R(i),'OMEGA'), continue; end

    iy = double(R(i).inv_info.iy);
    ix = double(R(i).inv_info.ix);
    if ~(isfinite(iy) && isfinite(ix)), continue; end
    if iy<1 || ix<1 || iy>szLC(1) || ix>szLC(2), continue; end

    lin = sub2ind(szLC, iy, ix);
    key = uint32(lin);

    om = R(i).OMEGA(:);
    om = om(isfinite(om));
    if isempty(om), continue; end

    if isKey(M, key)
        M(key) = [M(key); om]; %#ok<AGROW>
    else
        M(key) = om;
    end
end

ks = M.keys;
for j = 1:numel(ks)
    key = ks{j};
    lin = double(key);
    vals = M(key);
    if isempty(vals), continue; end
    medv = median(vals,'omitnan');
    [iy,ix] = ind2sub(szLC, lin);
    omega_pix_map(iy,ix) = medv;
    omega_pix_count(iy,ix) = numel(vals);
end
end


%% =======================================================================
%% ======================== QC 输出裁剪（结构不变） ========================
function qc = qc_prune_for_output(qc)
del = { ...
    'method','cond_thr','smin_rel_thr', ...
    'algorithm','alg_code','damping','hit_max_iter','final_cost', ...
    'Jopt_norm2','Jtb_maxabs','condK','smin','Jtb_minabs', ...
    'flag','flag_day','alg_code_map'};

for k = 1:numel(del)
    f = del{k};
    if isfield(qc, f)
        qc = rmfield(qc, f);
    end
end

if isfield(qc,'meta') && isstruct(qc.meta)
    meta_del = {'method','cond_thr','smin_rel_thr','alg_code_map'};
    for k = 1:numel(meta_del)
        f = meta_del{k};
        if isfield(qc.meta, f)
            qc.meta = rmfield(qc.meta, f);
        end
    end
    if isempty(fieldnames(qc.meta))
        qc = rmfield(qc,'meta');
    end
end
end


%% =======================================================================
%% =========================== 温度组织函数 ================================
function [Ct, TG] = build_effective_soil_temperature_scheme(SM_ref, Tsoil1, Tsoil2, CFG)
Ct = nan(size(SM_ref));
TG = nan(size(SM_ref));
mode = upper(string(CFG.DUAL_TG_MODE));

switch mode
    case "PAPER_CT"
        ok = isfinite(SM_ref) & SM_ref>=0;
        Ct(ok) = (SM_ref(ok) ./ CFG.CT_SMREF) .^ CFG.CT_EXP;
        TG = Tsoil2 + Ct .* (Tsoil1 - Tsoil2);

    case "TSOIL1_ONLY"
        TG = Tsoil1;

    case "TSOIL2_ONLY"
        TG = Tsoil2;

    otherwise
        error('未知 CFG.DUAL_TG_MODE=%s', string(CFG.DUAL_TG_MODE));
end
end


%% =======================================================================
%% ============================ 单温度残差/正演 ============================
function r = resid_halpha_single_temp(x, TBv, TBh, Ts, Tau, SM, Theta, CF, freq, omega_low, alpha0, lam_alpha, wV, wH)
h = x(1); alpha = x(2);
K = numel(TBv);
r = zeros(2*K+1,1);
sv = sqrt(wV); sh = sqrt(wH);
for k = 1:K
    [tbv_m, tbh_m] = tb_forward_single_temp(SM(k), Tau(k), h, alpha, omega_low, Ts(k), Theta(k), CF, freq, 1.0);
    r(2*k-1) = sv*(tbv_m - TBv(k));
    r(2*k)   = sh*(tbh_m - TBh(k));
end
r(end) = sqrt(lam_alpha) * (alpha - alpha0);
end

function r = resid_omega_block_single_temp(omega, TBv, TBh, Ts, Tau, SM, Theta, CF, freq, h_star, alpha_star, lam_smooth, omega_prev, wV, wH)
K = numel(TBv);
rvh = zeros(2*K,1);
sv = sqrt(wV); sh = sqrt(wH);
for k = 1:K
    [tbv_m, tbh_m] = tb_forward_single_temp(SM(k), Tau(k), h_star(k), alpha_star(k), omega, Ts(k), Theta(k), CF, freq, 1.0);
    rvh(2*k-1) = sv*(tbv_m - TBv(k));
    rvh(2*k)   = sh*(tbh_m - TBh(k));
end
if isfinite(omega_prev) && lam_smooth>0
    r = [rvh; sqrt(lam_smooth)*(omega - omega_prev)];
else
    r = rvh;
end
end

function [SM,VOD] = DDCA_single_temp(TBv,TBh,Ts,Tau_ini,h,CF,omega,porosity,Freq,Theta,alpha,LAMBDA_TAU)
opts = optimoptions('lsqnonlin','Display','off','MaxIterations',400,'FunctionTolerance',1e-6,'StepTolerance',1e-6);
fun = @(x) F_sm_single_temp(x,TBv,TBh,Ts,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU);
xhat = lsqnonlin(fun, [0.20;Tau_ini], [0.02;0], [porosity;5], opts);
SM = real(xhat(1)); VOD = real(xhat(2));
end

function Func = F_sm_single_temp(x,TBv,TBh,Ts,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU)
SM = x(1); Tau = x(2);
epsv = Mironov(Freq,SM,CF);
[rh, rv] = Fresnel(Theta, epsv);
Q = max(alpha.*h,0);
atten = exp(-h.*cosd(Theta).^2);
rh_r = ((1-Q).*rh + Q.*rv).*atten;
rv_r = ((1-Q).*rv + Q.*rh).*atten;
gamma = exp(-Tau);
Tbv_m = Ts.*((1-rv_r).*gamma + (1-omega).*(1-gamma).*(1+rv_r.*gamma));
Tbh_m = Ts.*((1-rh_r).*gamma + (1-omega).*(1-gamma).*(1+rh_r.*gamma));
Func = [Tbv_m-TBv; Tbh_m-TBh; LAMBDA_TAU.*(Tau-Tau_ini)];
end

function [TBv_m, Tbh_m] = tb_forward_single_temp(SM, Tau, h, alpha, omega, Ts, Theta, CF, freq, C)
epsv = Mironov(freq, SM, CF);
[rh, rv] = Fresnel(Theta, epsv);
Q = max(alpha*h,0);
atten = exp(-h*(cosd(Theta).^2));
rh_r = ((1-Q).*rh + Q.*rv).*atten;
rv_r = ((1-Q).*rv + Q.*rh).*atten;
gamma = exp(-Tau);
TBv_m = C*Ts .* ((1-rv_r).*gamma + (1-omega).*(1-gamma).*(1+rv_r.*gamma));
Tbh_m = C*Ts .* ((1-rh_r).*gamma + (1-omega).*(1-gamma).*(1+rh_r.*gamma));
end

function [rV, rH, rmseV, rmseH, rmseHV] = tb_rmse_block_single_temp(omega_hat, ib_use, TBv, TBh, Ts, Tau_star, SM_ref, IA, h_series, alpha_series, CF, freq)
K = numel(ib_use);
rV = nan(K,1); rH = nan(K,1);
for j=1:K
    k = ib_use(j);
    [tbv_m, tbh_m] = tb_forward_single_temp(SM_ref(k), Tau_star(k), h_series(k), alpha_series(k), omega_hat, Ts(k), IA(k), CF, freq, 1.0);
    rV(j) = TBv(k)-tbv_m;
    rH(j) = TBh(k)-tbh_m;
end
rmseV  = sqrt(mean(rV(isfinite(rV)).^2,'omitnan'));
rmseH  = sqrt(mean(rH(isfinite(rH)).^2,'omitnan'));
rmseHV = sqrt(mean([rV(isfinite(rV)); rH(isfinite(rH))].^2,'omitnan'));
end


%% =======================================================================
%% ============================ 双温度残差/正演 ============================
function r = resid_halpha_dual_temp(x, TBv, TBh, TC, TG, Tau, SM, Theta, CF, freq, omega_low, alpha0, lam_alpha, wV, wH)
h = x(1); alpha = x(2);
K = numel(TBv);
r = zeros(2*K+1,1);
sv = sqrt(wV); sh = sqrt(wH);
for k = 1:K
    [tbv_m, tbh_m] = tb_forward_dual_temp(SM(k), Tau(k), h, alpha, omega_low, TC(k), TG(k), Theta(k), CF, freq, 1.0);
    r(2*k-1) = sv*(tbv_m - TBv(k));
    r(2*k)   = sh*(tbh_m - TBh(k));
end
r(end) = sqrt(lam_alpha) * (alpha - alpha0);
end

function r = resid_omega_block_dual_temp(omega, TBv, TBh, TC, TG, Tau, SM, Theta, CF, freq, h_star, alpha_star, lam_smooth, omega_prev, wV, wH)
K = numel(TBv);
rvh = zeros(2*K,1);
sv = sqrt(wV); sh = sqrt(wH);
for k = 1:K
    [tbv_m, tbh_m] = tb_forward_dual_temp(SM(k), Tau(k), h_star(k), alpha_star(k), omega, TC(k), TG(k), Theta(k), CF, freq, 1.0);
    rvh(2*k-1) = sv*(tbv_m - TBv(k));
    rvh(2*k)   = sh*(tbh_m - TBh(k));
end
if isfinite(omega_prev) && lam_smooth>0
    r = [rvh; sqrt(lam_smooth)*(omega - omega_prev)];
else
    r = rvh;
end
end

function [SM,VOD] = DDCA_dual_temp(TBv,TBh,TC,TG,Tau_ini,h,CF,omega,porosity,Freq,Theta,alpha,LAMBDA_TAU)
opts = optimoptions('lsqnonlin','Display','off','MaxIterations',400,'FunctionTolerance',1e-6,'StepTolerance',1e-6);
fun = @(x) F_sm_dual_temp(x,TBv,TBh,TC,TG,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU);
xhat = lsqnonlin(fun, [0.20;Tau_ini], [0.02;0], [porosity;5], opts);
SM = real(xhat(1)); VOD = real(xhat(2));
end

function Func = F_sm_dual_temp(x,TBv,TBh,TC,TG,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU)
SM = x(1); Tau = x(2);
epsv = Mironov(Freq,SM,CF);
[rh, rv] = Fresnel(Theta, epsv);
Q = max(alpha.*h,0);
atten = exp(-h.*cosd(Theta).^2);
rh_r = ((1-Q).*rh + Q.*rv).*atten;
rv_r = ((1-Q).*rv + Q.*rh).*atten;
gamma = exp(-Tau);
Tbv_m = TG.*((1-rv_r).*gamma) + TC.*((1-omega).*(1-gamma).*(1+rv_r.*gamma));
Tbh_m = TG.*((1-rh_r).*gamma) + TC.*((1-omega).*(1-gamma).*(1+rh_r.*gamma));
Func = [Tbv_m-TBv; Tbh_m-TBh; LAMBDA_TAU.*(Tau-Tau_ini)];
end

function [TBv_m, Tbh_m] = tb_forward_dual_temp(SM, Tau, h, alpha, omega, TC, TG, Theta, CF, freq, C)
epsv = Mironov(freq, SM, CF);
[rh, rv] = Fresnel(Theta, epsv);
Q = max(alpha*h,0);
atten = exp(-h*(cosd(Theta).^2));
rh_r = ((1-Q).*rh + Q.*rv).*atten;
rv_r = ((1-Q).*rv + Q.*rh).*atten;
gamma = exp(-Tau);
TBv_m = C .* ( TG .* ((1-rv_r).*gamma) + TC .* ((1-omega).*(1-gamma).*(1+rv_r.*gamma)) );
Tbh_m = C .* ( TG .* ((1-rh_r).*gamma) + TC .* ((1-omega).*(1-gamma).*(1+rh_r.*gamma)) );
end

function [rV, rH, rmseV, rmseH, rmseHV] = tb_rmse_block_dual_temp(omega_hat, ib_use, TBv, TBh, TC, TG, Tau_star, SM_ref, IA, h_series, alpha_series, CF, freq)
K = numel(ib_use);
rV = nan(K,1); rH = nan(K,1);
for j=1:K
    k = ib_use(j);
    [tbv_m, tbh_m] = tb_forward_dual_temp(SM_ref(k), Tau_star(k), h_series(k), alpha_series(k), omega_hat, TC(k), TG(k), IA(k), CF, freq, 1.0);
    rV(j)=TBv(k)-tbv_m;
    rH(j)=TBh(k)-tbh_m;
end
rmseV  = sqrt(mean(rV(isfinite(rV)).^2,'omitnan'));
rmseH  = sqrt(mean(rH(isfinite(rH)).^2,'omitnan'));
rmseHV = sqrt(mean([rV(isfinite(rV)); rH(isfinite(rH))].^2,'omitnan'));
end


%% =======================================================================
%% =========================== QC 计算（保持结构） =========================
function qc = qc_compute_blocks_optionA(CFG, blkStarts, blkEnds, blkIndexCell, valid_tau, ...
    TBv, TBh, Ts, Tau_star, SM_ref, IA, h_series, alpha_series, OMEGA, CF, freq, wV, wH, BOUNDS_OMEGA, diag, temp_scheme, TC_use, TG_use, Ts_use)

Nt = numel(TBv);
Kb = numel(blkIndexCell);

qc = struct();
qc.enable = isfield(CFG,'QC_ENABLE') && CFG.QC_ENABLE;
qc.method = "OptionA_alpha_fixed";
qc.state  = "x=[omega,tau,h]";

qc.nmin   = getf(CFG,'QC_NMIN',3);
qc.cond_thr = getf(CFG,'QC_COND_THR',1e6);
qc.smin_rel_thr = getf(CFG,'QC_SMIN_REL_THR',1e-6);
qc.domega = getf(CFG,'QC_DOMEGA',1e-3);
qc.dtau   = getf(CFG,'QC_DTAU',1e-2);
qc.dh     = getf(CFG,'QC_DH',1e-2);

qc.block_start = blkStarts(:);
qc.block_end   = blkEnds(:);

qc.n_use        = zeros(Kb,1,'uint16');
qc.algorithm    = strings(Kb,1);
qc.alg_code     = zeros(Kb,1,'uint8');
qc.damping      = nan(Kb,1);
qc.exitflag     = nan(Kb,1);
qc.iter         = zeros(Kb,1,'uint16');
qc.hit_max_iter = false(Kb,1);
qc.final_cost   = nan(Kb,1);
qc.firstorderopt = nan(Kb,1);
qc.Tb_RMSE_V    = nan(Kb,1);
qc.Tb_RMSE_H    = nan(Kb,1);
qc.Tb_RMSE_HV   = nan(Kb,1);
qc.Jopt_norm2   = nan(Kb,1);
qc.Jtb_norm2    = nan(Kb,1);
qc.Jtb_rms      = nan(Kb,1);
qc.Jtb_maxabs   = nan(Kb,1);
qc.Jtb_minabs   = nan(Kb,1);

qc.condJ   = nan(Kb,1);
qc.condK   = nan(Kb,1);
qc.smin    = nan(Kb,1);
qc.sratio  = nan(Kb,1);

qc.flag     = int8(-9*ones(Kb,1));
qc.flag_day = int8(-9*ones(Nt,1));

qc.alg_code_map = struct('UNKNOWN',uint8(0),'TRR',uint8(1),'LM',uint8(2),'FIXED',uint8(9));

if ~qc.enable
    return;
end

sv = sqrt(wV);
sh = sqrt(wH);

try
    if isfield(diag,'n_use')        , qc.n_use         = diag.n_use; end
    if isfield(diag,'algorithm')    , qc.algorithm     = diag.algorithm; end
    if isfield(diag,'alg_code')     , qc.alg_code      = diag.alg_code; end
    if isfield(diag,'damping')      , qc.damping       = diag.damping; end
    if isfield(diag,'exitflag')     , qc.exitflag      = diag.exitflag; end
    if isfield(diag,'iter')         , qc.iter          = diag.iter; end
    if isfield(diag,'hit_max_iter') , qc.hit_max_iter  = diag.hit_max_iter; end
    if isfield(diag,'final_cost')   , qc.final_cost    = diag.final_cost; end
    if isfield(diag,'firstorderopt'), qc.firstorderopt = diag.firstorderopt; end
    if isfield(diag,'Tb_RMSE_V')    , qc.Tb_RMSE_V     = diag.Tb_RMSE_V; end
    if isfield(diag,'Tb_RMSE_H')    , qc.Tb_RMSE_H     = diag.Tb_RMSE_H; end
    if isfield(diag,'Tb_RMSE_HV')   , qc.Tb_RMSE_HV    = diag.Tb_RMSE_HV; end
    if isfield(diag,'Jopt_norm2')   , qc.Jopt_norm2    = diag.Jopt_norm2; end
    if isfield(diag,'Jtb_norm2')    , qc.Jtb_norm2     = diag.Jtb_norm2; end
    if isfield(diag,'Jtb_rms')      , qc.Jtb_rms       = diag.Jtb_rms; end
    if isfield(diag,'Jtb_maxabs')   , qc.Jtb_maxabs    = diag.Jtb_maxabs; end
    if isfield(diag,'Jtb_minabs')   , qc.Jtb_minabs    = diag.Jtb_minabs; end
catch
end

for bb = 1:Kb
    ib = blkIndexCell{bb};
    if isempty(ib), continue; end
    ib_use = ib(valid_tau(ib));

    if qc.n_use(bb)==0
        qc.n_use(bb) = uint16(numel(ib_use));
    end

    if qc.n_use(bb) < qc.nmin
        qc.flag(bb) = int8(0);
        qc.flag_day(ib_use) = qc.flag(bb);
        continue;
    end

    om_hat = median(double(OMEGA(ib_use)), 'omitnan');
    if ~isfinite(om_hat)
        qc.flag(bb) = int8(0);
        qc.flag_day(ib_use) = qc.flag(bb);
        continue;
    end

    try
        [condK, smin, sratio] = qc_block_jacobian_cond( ...
            om_hat, ib_use, TBv, TBh, Ts, Tau_star, SM_ref, IA, ...
            h_series, alpha_series, CF, freq, sv, sh, qc.domega, qc.dtau, qc.dh, BOUNDS_OMEGA, ...
            temp_scheme, TC_use, TG_use, Ts_use);

        qc.condJ(bb)  = condK;
        qc.condK(bb)  = condK;
        qc.smin(bb)   = smin;
        qc.sratio(bb) = sratio;

        % 保持"只记录不硬筛"的原则
        qc.flag(bb) = int8(1);
    catch
        qc.flag(bb) = int8(0);
    end

    qc.flag_day(ib_use) = qc.flag(bb);
end
end

function [condK, smin, sratio] = qc_block_jacobian_cond( ...
    omega0, ib_use, TBv, TBh, Ts, Tau_star, SM_ref, IA, ...
    h_series, alpha_series, CF, freq, sv, sh, domega, dtau, dh, BOUNDS_OMEGA, ...
    temp_scheme, TC_use, TG_use, Ts_use)

Kobs = numel(ib_use);
J = zeros(2*Kobs, 3);

for j = 1:Kobs
    k = ib_use(j);

    smk  = SM_ref(k);
    thk  = IA(k);
    tauk = Tau_star(k);

    hk = pick_one(h_series, k);
    ak = pick_one(alpha_series, k);

    op = min(max(omega0 + domega, BOUNDS_OMEGA(1)), BOUNDS_OMEGA(2));
    om = min(max(omega0 - domega, BOUNDS_OMEGA(1)), BOUNDS_OMEGA(2));
    if op == om
        op = min(max(omega0 + 2*domega, BOUNDS_OMEGA(1)), BOUNDS_OMEGA(2));
        om = min(max(omega0 - 2*domega, BOUNDS_OMEGA(1)), BOUNDS_OMEGA(2));
    end

    tp = max(0, tauk + dtau);
    tm = max(0, tauk - dtau);
    if tp == tm
        tp = max(0, tauk + 2*dtau);
        tm = max(0, tauk - 2*dtau);
    end

    hp = max(eps, hk + dh);
    hm = max(eps, hk - dh);
    if hp == hm
        hp = max(eps, hk + 2*dh);
        hm = max(eps, hk - 2*dh);
    end

    if upper(string(temp_scheme))=="ORIG_TS"
        [tbv_p, tbh_p] = tb_forward_single_temp(smk, tauk, hk, ak, op, Ts_use(k), thk, CF, freq, 1.0);
        [tbv_m, tbh_m] = tb_forward_single_temp(smk, tauk, hk, ak, om, Ts_use(k), thk, CF, freq, 1.0);
        dTb_domega_v = (tbv_p - tbv_m) / max(eps, (op - om));
        dTb_domega_h = (tbh_p - tbh_m) / max(eps, (op - om));

        [tbv_p, tbh_p] = tb_forward_single_temp(smk, tp, hk, ak, omega0, Ts_use(k), thk, CF, freq, 1.0);
        [tbv_m, tbh_m] = tb_forward_single_temp(smk, tm, hk, ak, omega0, Ts_use(k), thk, CF, freq, 1.0);
        dTb_dtau_v = (tbv_p - tbv_m) / max(eps, (tp - tm));
        dTb_dtau_h = (tbh_p - tbh_m) / max(eps, (tp - tm));

        [tbv_p, tbh_p] = tb_forward_single_temp(smk, tauk, hp, ak, omega0, Ts_use(k), thk, CF, freq, 1.0);
        [tbv_m, tbh_m] = tb_forward_single_temp(smk, tauk, hm, ak, omega0, Ts_use(k), thk, CF, freq, 1.0);
        dTb_dh_v = (tbv_p - tbv_m) / max(eps, (hp - hm));
        dTb_dh_h = (tbh_p - tbh_m) / max(eps, (hp - hm));
    else
        [tbv_p, tbh_p] = tb_forward_dual_temp(smk, tauk, hk, ak, op, TC_use(k), TG_use(k), thk, CF, freq, 1.0);
        [tbv_m, tbh_m] = tb_forward_dual_temp(smk, tauk, hk, ak, om, TC_use(k), TG_use(k), thk, CF, freq, 1.0);
        dTb_domega_v = (tbv_p - tbv_m) / max(eps, (op - om));
        dTb_domega_h = (tbh_p - tbh_m) / max(eps, (op - om));

        [tbv_p, tbh_p] = tb_forward_dual_temp(smk, tp, hk, ak, omega0, TC_use(k), TG_use(k), thk, CF, freq, 1.0);
        [tbv_m, tbh_m] = tb_forward_dual_temp(smk, tm, hk, ak, omega0, TC_use(k), TG_use(k), thk, CF, freq, 1.0);
        dTb_dtau_v = (tbv_p - tbv_m) / max(eps, (tp - tm));
        dTb_dtau_h = (tbh_p - tbh_m) / max(eps, (tp - tm));

        [tbv_p, tbh_p] = tb_forward_dual_temp(smk, tauk, hp, ak, omega0, TC_use(k), TG_use(k), thk, CF, freq, 1.0);
        [tbv_m, tbh_m] = tb_forward_dual_temp(smk, tauk, hm, ak, omega0, TC_use(k), TG_use(k), thk, CF, freq, 1.0);
        dTb_dh_v = (tbv_p - tbv_m) / max(eps, (hp - hm));
        dTb_dh_h = (tbh_p - tbh_m) / max(eps, (hp - hm));
    end

    r = 2*j-1;
    J(r,   1) = sv * dTb_domega_v;
    J(r,   2) = sv * dTb_dtau_v;
    J(r,   3) = sv * dTb_dh_v;

    J(r+1, 1) = sh * dTb_domega_h;
    J(r+1, 2) = sh * dTb_dtau_h;
    J(r+1, 3) = sh * dTb_dh_h;
end

colScale = max(abs(J), [], 1);
colScale(colScale<=0 | ~isfinite(colScale)) = 1;
Js = J ./ colScale;

s = svd(Js, 'econ');
if isempty(s)
    condK = Inf; smin = 0; sratio = 0;
    return;
end
s1 = s(1);
smin = s(end);
if smin <= 0
    condK = Inf;
else
    condK = s1 / smin;
end
sratio = smin / max(eps, s1);
end


%% =======================================================================
%% ============================ Tau / GLDAS工具 ============================
function Tau_ini = Tau(NDVI, NDVI_max, NDVI_min, Landcover, b, sf, theta, mode_vwc2)

NDVI(NDVI<0 | NDVI>1) = nan;

[m,n] = size(NDVI); %#ok<ASGLU>
VWC2 = zeros(m,n);

% ===== 叶片项：保持不变 =====
VWC1 = 1.9134*(NDVI.^2) - 0.3215*NDVI;

mode_vwc2 = upper(string(mode_vwc2));

is_crop_grass = (Landcover == 10) | (Landcover == 12);
is_other      = ~is_crop_grass;
is_other(Landcover==0) = false;

switch mode_vwc2

    case "NDVIMIN"
        % ===== 方案1：你当前原始写法 =====
        % 草地/农田：sf/(1-NDVImin) * (NDVI - NDVImin)
        VWC2(is_crop_grass) = ...
            sf(is_crop_grass) ./ (1 - NDVI_min(is_crop_grass)) .* ...
            (NDVI(is_crop_grass) - NDVI_min(is_crop_grass));

        % 其他地类：sf/(1-NDVImin) * (NDVImax - NDVImin)
        VWC2(is_other) = ...
            sf(is_other) ./ (1 - NDVI_min(is_other)) .* ...
            (NDVI_max(is_other) - NDVI_min(is_other));

    case "POINT1"
        % ===== 方案2：0.1 公式 =====
        % 草地/农田：用当天 NDVI 作为参考上端
        den_crop = (NDVI(is_crop_grass) - 0.1) ./ 0.9;
        VWC2(is_crop_grass) = sf(is_crop_grass) .* den_crop;

        % 其他地类：用 NDVImax 作为参考上端
        den_other = (NDVI_max(is_other) - 0.1) ./ 0.9;
        VWC2(is_other) = sf(is_other) .* den_other;

    otherwise
        error('未知 CFG.TAU_VWC2_MODE=%s', string(mode_vwc2));
end

VWC2(Landcover==0) = nan;


VWC = VWC1 + VWC2;
VWC(VWC>30 | isinf(VWC)) = nan;

Tau_ini = b .* VWC .* secd(theta);
Tau_ini(Tau_ini<0 | Tau_ini>5) = nan;

end

function IDX = build_gldas_file_index(folder)
L = dir(fullfile(folder,'*.mat'));
n = numel(L);
if n==0, error('GLDAS mat 文件夹为空：%s', folder); end
t_utc = NaT(n,1);
keep = false(n,1);
for i = 1:n
    tok = regexp(L(i).name, '^(\d{8})_(\d{4})\.mat$', 'tokens', 'once');
    if isempty(tok), continue; end
    t_utc(i) = datetime([tok{1} tok{2}], 'InputFormat','yyyyMMddHHmm');
    keep(i) = true;
end
IDX.files = L(keep);
IDX.t_utc = t_utc(keep);
[IDX.t_utc, ord] = sort(IDX.t_utc);
IDX.files = IDX.files(ord);
end

function t_utc = local_overpass_to_utc_vec(day_dt, lon_vec, local_hour)
base_day = dateshift(day_dt,'start','day');
utc_hour = local_hour - lon_vec(:)/15;
t_utc = base_day + hours(utc_hour);
end

function idx_pick = pick_gldas_file_indices(gldas_times, target_times, tol_hours)
n = numel(target_times);
idx_pick = nan(n,1);
for i=1:n
    if isnat(target_times(i)), continue; end
    dt = abs(hours(gldas_times - target_times(i)));
    [dmin, idx] = min(dt);
    if ~isempty(idx) && isfinite(dmin) && dmin <= tol_hours
        idx_pick(i) = idx;
    end
end
end

function T = get_dates_from_folder(folder)
L = dir(fullfile(folder,'*.mat'));
if isempty(L)
    T = NaT(0,1);
    return;
end
T = Get_date(L);
if isnumeric(T), T = datetime(T,'ConvertFrom','datenum'); end
T = dateshift(T(:),'start','day');
end


%% =======================================================================
%% ============================ 任务/筛选工具 =============================
function [network, station, st_lat, st_lon, keys, grid_mesh, preMapped] = build_task_list(CFG, LC, lat_9km, lon_9km, grid_mesh_ismn, grid_id, has_grid_latlon, grid_lat, grid_lon)
if upper(string(CFG.RUN_DOMAIN))=="GLOBAL"
    preMapped = true;
    ok_pix = isfinite(LC);
    grid_mesh = find(ok_pix);
    keys = "G_" + string(grid_mesh);
    network = strings(numel(grid_mesh),1);
    station = keys;
    st_lat = lat_9km(grid_mesh);
    st_lon = lon_9km(grid_mesh);
else
    switch upper(string(CFG.LIST_MODE))
        case "CSV"
            Tcsv = readtable(CFG.station_csv);
            network = string(Tcsv.network);
            station = string(Tcsv.station);
            st_lat  = Tcsv.latitude;
            st_lon  = Tcsv.longitude;
            keys = network + "_" + station;
            grid_mesh = nan(height(Tcsv),1);
            preMapped = false;
        case "ISMN_ALL"
            keys = string(grid_id);
            Nall = numel(keys);
            network = strings(Nall,1);
            station = strings(Nall,1);
            for i=1:Nall
                parts = split(keys(i), "_");
                if numel(parts)>=2
                    network(i)=parts(1);
                    station(i)=strjoin(parts(2:end), "_");
                else
                    station(i)=keys(i);
                end
            end
            if has_grid_latlon
                st_lat = grid_lat;
                st_lon = grid_lon;
            else
                st_lat = lat_9km(grid_mesh_ismn);
                st_lon = lon_9km(grid_mesh_ismn);
            end
            grid_mesh = grid_mesh_ismn;
            preMapped = true;
        otherwise
            error('未知 LIST_MODE=%s', string(CFG.LIST_MODE));
    end
end
end

function [network, station, st_lat, st_lon, keys, grid_mesh, grid, grid_id, grid_lat, grid_lon] = ...
    filter_ismn_candidates(CFG, tvec, t_grid, grid, grid_id, grid_mesh, ...
    network, station, st_lat, st_lon, keys, ...
    LC, mask_static_ok, has_grid_latlon, grid_lat, grid_lon)

rng(CFG.random_seed,'twister');

if isnumeric(t_grid)
    t_grid = datetime(t_grid,'ConvertFrom','datenum');
end

tvec_day  = dateshift(tvec,'start','day');
tgrid_day = dateshift(t_grid,'start','day');

[~, idx_cols] = ismember(tvec_day, tgrid_day);
cols = idx_cols(idx_cols>0);

Nall = numel(grid_mesh);
cls_vec = nan(Nall,1);
ok_cand = false(Nall,1);

valid_classes = setdiff(0:16, CFG.exclude_classes(:).');

for i = 1:Nall
    [iy,ix] = ind2sub(size(LC), grid_mesh(i));

    if ~mask_static_ok(iy,ix), continue; end
    cls = LC(iy,ix);
    if ~ismember(cls, valid_classes), continue; end
    cls_vec(i) = cls;

    if upper(string(CFG.SM_SOURCE))=="ISMN" && ~isempty(cols)
        v = grid(i, cols);
        nvd = sum(isfinite(v) & v>=-0.01 & v<=1.0);
    else
        nvd = CFG.ismn_min_days;
    end

    if nvd >= CFG.ismn_min_days
        ok_cand(i) = true;
    end
end

fprintf('[SELECT] 候选数：%d / %d\n', nnz(ok_cand), Nall);
if nnz(ok_cand)==0
    error('[SELECT] 无候选：检查 ismn_min_days / t_grid / 数据有效性');
end

keep_mask = false(Nall,1);
mode = upper(string(CFG.ISMN_ALL_RUNMODE));

if mode=="ALL"
    keep_mask = ok_cand;
elseif mode=="SAMPLE"
    uca = sort(unique(cls_vec(ok_cand & isfinite(cls_vec))));
    fprintf('[SELECT] SAMPLE：每类抽 %d\n', CFG.n_per_class);
    for ii = 1:numel(uca)
        cc = uca(ii);
        idx = find(ok_cand & cls_vec==cc);
        n_c = numel(idx);
        n_u = min(CFG.n_per_class, n_c);
        if n_u > 0
            sel = idx(randperm(n_c, n_u));
            keep_mask(sel) = true;
        end
        fprintf('   - 类 %2d : 候选=%4d, 抽样=%4d\n', cc, n_c, n_u);
    end
else
    error('未知 CFG.ISMN_ALL_RUNMODE=%s', string(CFG.ISMN_ALL_RUNMODE));
end

network   = network(keep_mask);
station   = station(keep_mask);
st_lat    = st_lat(keep_mask);
st_lon    = st_lon(keep_mask);
keys      = keys(keep_mask);
grid_mesh = grid_mesh(keep_mask);

if ~isempty(grid), grid = grid(keep_mask,:); end
if ~isempty(grid_id), grid_id = grid_id(keep_mask); end
if has_grid_latlon
    if ~isempty(grid_lat), grid_lat = grid_lat(keep_mask); end
    if ~isempty(grid_lon), grid_lon = grid_lon(keep_mask); end
end
end

function [network, station, st_lat, st_lon, keys, grid_mesh, grid, grid_id, grid_lat, grid_lon] = ...
    apply_target_key_filter(CFG, network, station, st_lat, st_lon, keys, grid_mesh, grid, grid_id, has_grid_latlon, grid_lat, grid_lon)

target_keys = string(CFG.target_keys(:));
keys = string(keys(:));
keep_mask = ismember(keys, target_keys);

network   = network(keep_mask);
station   = station(keep_mask);
st_lat    = st_lat(keep_mask);
st_lon    = st_lon(keep_mask);
keys      = keys(keep_mask);
grid_mesh = grid_mesh(keep_mask);

if ~isempty(grid), grid = grid(keep_mask,:); end
if ~isempty(grid_id), grid_id = grid_id(keep_mask); end
if has_grid_latlon
    grid_lat = grid_lat(keep_mask);
    grid_lon = grid_lon(keep_mask);
end
end

function [iy_list, ix_list, cls_list, grid_row_list, warn_cnt] = premap_tasks(preMapped, grid_mesh_use, grid_row_use, keys_use, lat_use, lon_use, LC, lat_9km, lon_9km, grid_id, grid_mesh_ismn, has_grid_latlon, grid_lat, grid_lon)
Nst = numel(keys_use);
iy_list=nan(Nst,1);
ix_list=nan(Nst,1);
cls_list=nan(Nst,1);
grid_row_list=nan(Nst,1);
warn_cnt=0;
for s=1:Nst
    if preMapped
        [iy, ix] = ind2sub(size(LC), grid_mesh_use(s));
        grid_row_list(s) = grid_row_use(s);
    else
        key = keys_use(s); lat0=lat_use(s); lon0=lon_use(s);
        hit = find(contains(grid_id, key, 'IgnoreCase', true));
        if numel(hit)>=1
            if numel(hit)>1 && has_grid_latlon && isfinite(lat0) && isfinite(lon0)
                d = (grid_lat(hit)-lat0).^2 + (grid_lon(hit)-lon0).^2; [~,ii] = min(d); hit = hit(ii);
            else
                hit = hit(1);
            end
            grid_row_list(s)=hit;
            [iy, ix] = ind2sub(size(LC), grid_mesh_ismn(hit));
        else
            d = (lat_9km-lat0).^2 + (lon_9km-lon0).^2; [~,mesh] = min(d(:));
            [iy, ix] = ind2sub(size(LC), mesh); warn_cnt = warn_cnt + 1;
        end
    end
    iy_list(s)=iy;
    ix_list(s)=ix;
    cls_list(s)=LC(iy,ix);
end
end


%% =======================================================================
%% =============================== 杂项工具 ================================
function use_idx = shard_indices(all_idx, N, ID, mode)
mode = lower(string(mode));
switch mode
    case "roundrobin"
        use_idx = all_idx(mod(all_idx-1, N) + 1 == ID);
    case "contiguous"
        nAll = numel(all_idx);
        edges = round(linspace(0, nAll, N+1));
        a = edges(ID)+1;
        b = edges(ID+1);
        if a>b, use_idx = all_idx([]); else, use_idx = all_idx(a:b); end
    otherwise
        error('未知 SHARD.MODE=%s', mode);
end
end

function [blkStarts, blkEnds, blkIndexCell] = make_viirs8_blocks(tvec)
tvec = dateshift(tvec,'start','day');

doy = day(tvec,'dayofyear');
yy  = year(tvec);

blkStartsAll = datetime(yy,1,1) + days(8*floor((doy-1)/8));
[blkStarts,~,ic] = unique(blkStartsAll,'stable');

Kb = numel(blkStarts);
blkEnds = NaT(Kb,1);
blkIndexCell = cell(Kb,1);

for k = 1:Kb
    ib = find(ic==k);
    blkIndexCell{k} = ib;
    blkEnds(k) = tvec(ib(end));   % 真实结束日，不超过该年最后一天
end
end

function [usePar, pool] = setup_parpool(PAR)
usePar = false;
pool = [];
if ~isfield(PAR,'ENABLE') || ~PAR.ENABLE, return; end
hasPCT = ~isempty(ver('parallel')) || license('test','Distrib_Computing_Toolbox');
if ~hasPCT, return; end
nw = PAR.NUM_WORKERS;
if isempty(nw), nw = auto_detect_workers(); end
if isfinite(PAR.MAX_WORKERS), nw = min(nw, PAR.MAX_WORKERS); end
nw = max(1, floor(nw));

pool = gcp('nocreate');
if ~isempty(pool) && pool.NumWorkers ~= nw
    try, delete(pool); catch, end
    pool = [];
end
if isempty(pool)
    try, pool = parpool('local', nw, 'IdleTimeout', Inf); catch, pool = []; end
end
pctRunOnAll setenv('OMP_NUM_THREADS','1');
pctRunOnAll setenv('MKL_NUM_THREADS','1');
pctRunOnAll setenv('OPENBLAS_NUM_THREADS','1');
pctRunOnAll setenv('VECLIB_MAXIMUM_THREADS','1');
usePar = ~isempty(pool);
end

function nw = auto_detect_workers()
nw = str2double(getenv('SLURM_CPUS_PER_TASK'));
if ~(isfinite(nw) && nw>=1)
    try, nw = feature('numcores'); catch, nw = 4; end
end
end

function handle_msg(m, N, keys, shard_tag, CFG) %#ok<INUSD>
persistent t0 done fail
if isempty(t0), t0=tic; done=0; fail=0; end
ts = datestr(now,'HH:MM:SS.FFF');
key = "";
if isfield(m,'p') && m.p>=1 && m.p<=numel(keys)
    key = keys(m.p);
end
switch m.type
    case 'start'
        fprintf('%s  [%s][%03d] START  %s\n', ts, shard_tag, m.p, key);
    case 'done'
        done = done + 1;
        if isfield(m,'msg')
            fprintf('%s  [%s][%03d] DONE   %s | %s\n', ts, shard_tag, m.p, key, m.msg);
        else
            fprintf('%s  [%s][%03d] DONE   %s\n', ts, shard_tag, m.p, key);
        end
    case 'fail'
        fail = fail + 1;
        fprintf('%s  [%s][%03d] FAIL   %s | %s\n', ts, shard_tag, m.p, key, m.msg);
    case 'step2_prog'
        fprintf('%s  [%s][%03d] STEP2  %s | %d/%d | %s\n', ts, shard_tag, m.p, key, m.kk, m.K, m.date);
    case 'step2_done'
        fprintf('%s  [%s][%03d] OMEGA  %s | %s\n', ts, shard_tag, m.p, key, m.msg);
end
proc = done + fail;
fprintf('%s  [%s][PROG] %5.1f%% | 处理=%3d/%3d | 成功=%3d 失败=%3d | 用时=%.1fs\n', ...
    ts, shard_tag, 100*proc/max(1,N), proc, N, done, fail, toc(t0));
end

function emit(dq, m)
try
    if ~isempty(dq), send(dq, m); end
catch
end
end

function tag = worker_tag()
try
    t = getCurrentTask();
    if isempty(t), id = 0; else, id = t.ID; end
catch
    id = 0;
end
tag = sprintf('W%02d', mod(id,100));
end

function v = pick_field(S, name)
if isfield(S, name)
    v = S.(name);
else
    v = [];
end
end

function v = pick_one(x, k)
if isscalar(x)
    v = x;
else
    v = x(k);
end
end

function v = getf(S, name, def)
try
    if isfield(S, name) && ~isempty(S.(name))
        v = S.(name);
    else
        v = def;
    end
catch
    v = def;
end
end

function y = iff(cond, a, b)
if cond
    y = a;
else
    y = b;
end
end

function code = alg_code_from_str(algStr)
s = lower(string(algStr));
code = uint8(0);
if contains(s,"trust") || contains(s,"reflective")
    code = uint8(1);
elseif contains(s,"levenberg") || contains(s,"marquardt") || contains(s,"lm")
    code = uint8(2);
elseif contains(s,"fixed")
    code = uint8(9);
end
end

function tf = should_apply_spike_cleaning(CFG)
tf = false;

if ~isfield(CFG,'SPIKE') || ~isstruct(CFG.SPIKE)
    return;
end
if ~isfield(CFG.SPIKE,'enable') || ~CFG.SPIKE.enable
    return;
end

mode_apply = "FY";
if isfield(CFG.SPIKE,'apply_to') && ~isempty(CFG.SPIKE.apply_to)
    mode_apply = upper(string(CFG.SPIKE.apply_to));
end

tb_src = upper(string(CFG.TB_SOURCE));

switch mode_apply
    case "FY"
        tf = (tb_src == "FY");
    case "SMAP"
        tf = (tb_src == "SMAP");
    case "ALL"
        tf = (tb_src == "FY" || tb_src == "SMAP");
    case "NONE"
        tf = false;
    otherwise
        error('未知 CFG.SPIKE.apply_to=%s，允许值： "FY" | "SMAP" | "ALL" | "NONE"', string(CFG.SPIKE.apply_to));
end
end

function [thr_v, thr_h] = get_station_spike_thresholds(key, CFG)
thr_v = CFG.SPIKE.default_TBv_thr;
thr_h = CFG.SPIKE.default_TBh_thr;
if ~isfield(CFG,'SPIKE') || ~isfield(CFG.SPIKE,'station_keys') || isempty(CFG.SPIKE.station_keys)
    return;
end
keys = string(CFG.SPIKE.station_keys(:));
idx = find(keys == string(key), 1, 'first');
if ~isempty(idx)
    thr_v = CFG.SPIKE.station_TBv_thr(idx);
    thr_h = CFG.SPIKE.station_TBh_thr(idx);
end
end

function [x_clean, bad] = remove_isolated_spikes(x, thr)
x = x(:);
n = numel(x);
x_clean = x;
bad = false(n,1);

if n < 3 || ~isfinite(thr) || thr <= 0
    return;
end

for k = 1:n
    if ~isfinite(x(k)), continue; end

    iL = k - 1;
    while iL >= 1 && ~isfinite(x(iL))
        iL = iL - 1;
    end

    iR = k + 1;
    while iR <= n && ~isfinite(x(iR))
        iR = iR + 1;
    end

    if iL < 1 || iR > n, continue; end

    d1 = x(k) - x(iL);
    d2 = x(k) - x(iR);

    if abs(d1) >= thr && abs(d2) >= thr && sign(d1) == sign(d2)
        bad(k) = true;
    end
end

x_clean(bad) = NaN;
end

function hval = read_h_year_pixel(CFG, year_int, iy, ix)
f = fullfile(CFG.h_year_folder, sprintf(CFG.h_year_pattern, year_int));
if ~exist(f,'file')
    error('YEARFILE_HQFIX: 找不到年度 h 文件：%s', f);
end

try
    M = matfile(f);
    if ~ismember(CFG.h_year_varname, who(M))
        error('YEARFILE_HQFIX: %s 里找不到变量 %s', f, CFG.h_year_varname);
    end
    hval = M.(CFG.h_year_varname)(iy, ix);
    hval = double(hval);
catch ME
    error('YEARFILE_HQFIX: 读取 %s(%d,%d) 失败：%s', f, iy, ix, ME.message);
end
end

function omega_val = pick_omega_fixed_pft(omega_pft, cls)
omega_val = NaN;
if isempty(omega_pft), return; end
idx = double(cls) + 1;
if idx>=1 && idx<=numel(omega_pft)
    omega_val = omega_pft(idx);
end
end

function omega_val = pick_omega_fixed_pixel(omega_pix_map, iy, ix)
omega_val = NaN;
if isempty(omega_pix_map), return; end
if iy>=1 && iy<=size(omega_pix_map,1) && ix>=1 && ix<=size(omega_pix_map,2)
    omega_val = omega_pix_map(iy,ix);
end
end

function lambda_star = pick_lcurve_corner(lambda_list, misfit, rough)
lambda_star = NaN;
ok = isfinite(lambda_list) & isfinite(misfit) & isfinite(rough) & misfit>0 & rough>0;
if nnz(ok) < 3, return; end

x = log10(misfit(ok));
y = log10(rough(ok));
lam = lambda_list(ok);

kappa = nan(numel(x),1);
for i = 2:numel(x)-1
    x1 = x(i-1); x2 = x(i); x3 = x(i+1);
    y1 = y(i-1); y2 = y(i); y3 = y(i+1);

    dx1 = x2 - x1; dy1 = y2 - y1;
    dx2 = x3 - x2; dy2 = y3 - y2;

    num = abs(dx1*dy2 - dy1*dx2);
    den = max(eps, (dx1^2 + dy1^2)^(3/2));
    kappa(i) = num / den;
end

[~, imax] = max(kappa);
if isfinite(imax) && imax>=1 && imax<=numel(lam)
    lambda_star = lam(imax);
end
end
function M = get_match_info_one(MATCH_INFO, s)
if isempty(MATCH_INFO)
    M = [];
else
    M = MATCH_INFO{s};
end
end
function TAB = build_gldas_day_slot_table(GLDAS_INDEX)
tday = dateshift(GLDAS_INDEX.t_utc,'start','day');
uday = unique(tday);
nDay = numel(uday);

slot_hours = hour(GLDAS_INDEX.t_utc) + minute(GLDAS_INDEX.t_utc)/60;
slot_u = unique(slot_hours);
slot_u = sort(slot_u(:));
nSlot = numel(slot_u);

gidx_mat = nan(nDay, nSlot);

for i = 1:numel(GLDAS_INDEX.t_utc)
    d = tday(i);
    h = slot_hours(i);

    id = find(uday == d, 1, 'first');
    ih = find(abs(slot_u - h) < 1e-10, 1, 'first');

    if ~isempty(id) && ~isempty(ih)
        gidx_mat(id, ih) = i;
    end
end

TAB = struct();
TAB.days = uday;
TAB.slot_hours = slot_u;
TAB.gidx_mat = gidx_mat;
end

function idx_row = get_day_slot_index_row(TAB, day_dt)
idx_row = nan(1, size(TAB.gidx_mat,2));
id = find(TAB.days == dateshift(day_dt,'start','day'), 1, 'first');
if ~isempty(id)
    idx_row = TAB.gidx_mat(id,:);
end
end
function [wV, wH] = get_weights(CFG)
wV = 1; wH = 1;
mode = upper(string(CFG.WEIGHT_MODE));
switch mode
    case "EQUAL"
        wV = 1; wH = 1;
    case "INVVAR_FROM_EXP0"
        if ~exist(CFG.weights_file,'file')
            error("缺少 weights_file=%s。请先用 Exp0 跑一遍再生成。", CFG.weights_file);
        end
        S = load(CFG.weights_file,'wV','wH');
        wV = S.wV; wH = S.wH;
    otherwise
        error("未知 WEIGHT_MODE=%s", mode);
end
end


function [h_star, alpha_star] = load_exp0_calib(CFG, iy, ix, LCij)
f = fullfile(CFG.exp0_calib_dir, sprintf('exp0_calib_pix_%d_%d.mat', iy, ix));
if ~exist(f,'file')
    error("Exp1a 需要 Exp0 的率定结果，但找不到 %s。", f);
end
S = load(f,'h_star','alpha_star','PFT');
h_star = S.h_star;
alpha_star = S.alpha_star;
if ~isfinite(h_star) || ~isfinite(alpha_star)
    error("Exp0 calib 含 NaN：%s", f);
end
end
function MATCH = build_match_models_for_pixels(CFG, lin_pix)

Np = numel(lin_pix);

t_req = datetime(CFG.match_start_date,'InputFormat','yyyyMMdd') : ...
        datetime(CFG.match_end_date,'InputFormat','yyyyMMdd');

T_b = Get_date(dir(fullfile(CFG.match_fy3b_folder,'*.mat')));
T_d = Get_date(dir(fullfile(CFG.match_fy3d_folder,'*.mat')));

if isnumeric(T_b), T_b = datetime(T_b,'ConvertFrom','datenum'); end
if isnumeric(T_d), T_d = datetime(T_d,'ConvertFrom','datenum'); end

t_train = intersect(t_req, intersect(T_b, T_d));
t_train = dateshift(t_train,'start','day');

assert(~isempty(t_train), '[MATCH] 训练期 FY3B/FY3D 没有共同日期。');

Nt = numel(t_train);

TBv_B = nan(Nt, Np);
TBh_B = nan(Nt, Np);
TBv_D = nan(Nt, Np);
TBh_D = nan(Nt, Np);

fprintf('[MATCH] 训练共同日期数：%d\n', Nt);

for k = 1:Nt
    name = datestr(t_train(k), 'yyyymmdd');
    fb = fullfile(CFG.match_fy3b_folder, [name '.mat']);
    fd = fullfile(CFG.match_fy3d_folder, [name '.mat']);

    Sb = load(fb, 'TBv', 'TBh');
    Sd = load(fd, 'TBv', 'TBh');

    if k == 1
        fprintf('\n[DEBUG-MATCH] first train day = %s\n', name);
        fprintf('[DEBUG-MATCH] FY3B file = %s\n', fb);
        fprintf('[DEBUG-MATCH] FY3D file = %s\n', fd);

        fprintf('[DEBUG-MATCH] size(Sb.TBv)=%s class=%s numel=%d\n', ...
            mat2str(size(Sb.TBv)), class(Sb.TBv), numel(Sb.TBv));
        fprintf('[DEBUG-MATCH] size(Sb.TBh)=%s class=%s numel=%d\n', ...
            mat2str(size(Sb.TBh)), class(Sb.TBh), numel(Sb.TBh));

        fprintf('[DEBUG-MATCH] size(Sd.TBv)=%s class=%s numel=%d\n', ...
            mat2str(size(Sd.TBv)), class(Sd.TBv), numel(Sd.TBv));
        fprintf('[DEBUG-MATCH] size(Sd.TBh)=%s class=%s numel=%d\n', ...
            mat2str(size(Sd.TBh)), class(Sd.TBh), numel(Sd.TBh));

        fprintf('[DEBUG-MATCH] size(lin_pix)=%s min=%g max=%g\n', ...
            mat2str(size(lin_pix)), min(lin_pix), max(lin_pix));

        fprintf('[DEBUG-MATCH] max(lin_pix)<=numel(Sb.TBv) ? %d\n', max(lin_pix) <= numel(Sb.TBv));
        fprintf('[DEBUG-MATCH] max(lin_pix)<=numel(Sd.TBv) ? %d\n', max(lin_pix) <= numel(Sd.TBv));
    end

    TBv_B(k,:) = double(Sb.TBv(lin_pix));
    TBh_B(k,:) = double(Sb.TBh(lin_pix));
    TBv_D(k,:) = double(Sd.TBv(lin_pix));
    TBh_D(k,:) = double(Sd.TBh(lin_pix));
end

MATCH = struct();
MATCH.method = string(CFG.MATCH_METHOD);
MATCH.Np = Np;

MATCH.V = fit_match_one_pol(TBv_B, TBv_D, CFG.MATCH_METHOD, CFG.match_min_valid_n);
MATCH.H = fit_match_one_pol(TBh_B, TBh_D, CFG.MATCH_METHOD, CFG.match_min_valid_n);
end
function M = fit_match_one_pol(Xraw, Yref, method_name, min_valid_n)

[~, Np] = size(Xraw);

M = struct();
M.method = string(method_name);
M.n_valid = zeros(1, Np);

switch lower(string(method_name))
    case "bias"
        M.a = nan(1, Np);
        M.b = nan(1, Np);

        for p = 1:Np
            x = Xraw(:,p);
            y = Yref(:,p);
            valid = isfinite(x) & isfinite(y);
            n = nnz(valid);
            M.n_valid(p) = n;

            if n < min_valid_n
                M.a(p) = 1.0;
                M.b(p) = 0.0;
                continue;
            end

            xx = [x(valid), ones(n,1)];
            coeff = regress(y(valid), xx);
            M.a(p) = coeff(1);
            M.b(p) = coeff(2);
        end

    case "cdf"
        M.raw_sorted = cell(1, Np);
        M.ref_sorted = cell(1, Np);

        for p = 1:Np
            x = Xraw(:,p);
            y = Yref(:,p);
            valid = isfinite(x) & isfinite(y);
            n = nnz(valid);
            M.n_valid(p) = n;

            if n < min_valid_n
                M.raw_sorted{p} = [];
                M.ref_sorted{p} = [];
                continue;
            end

            xs = sort(x(valid));
ys = sort(y(valid));

M.raw_sorted{p} = xs(:);
M.ref_sorted{p} = ys(:);
        end

    otherwise
        error('[MATCH] 未知 method_name=%s', string(method_name));
end
end
function x_adj = apply_match_row(x_row, M, method_name, allow_extrap)

orig_size = size(x_row);
x = x_row(:);   % 统一转列向量
x_adj = x;

switch lower(string(method_name))
    case "bias"
        a = M.a(:);
        b = M.b(:);

        valid_model = isfinite(a) & isfinite(b);
        valid_x = isfinite(x);
        idx = valid_model & valid_x;

        x_adj(idx) = a(idx) .* x(idx) + b(idx);

    case "cdf"
        for p = 1:numel(x)
            if ~isfinite(x(p))
                continue;
            end

            xr = M.raw_sorted{p};
            yr = M.ref_sorted{p};

            if isempty(xr) || isempty(yr)
                continue;
            end

            if ~allow_extrap
                if x(p) < min(xr) || x(p) > max(xr)
                    x_adj(p) = nan;
                    continue;
                end
            end

            [~, id] = min(abs(xr - x(p)));
            x_adj(p) = yr(id);
        end

    otherwise
        % none 或未知时直接返回原值
end

x_adj = reshape(x_adj, orig_size);
end
function NDVI_clim_max = build_ndvi_clim_max(ndvi_clim_folder, varname)

NDVI_clim_max = [];

for doy = 1:366
    f = fullfile(ndvi_clim_folder, sprintf('%d.mat', doy));
    if exist(f,'file')~=2
        error('缺少 NDVI_clim 文件：%s', f);
    end

    S = load(f, varname);
    X = double(S.(varname));

    if isempty(NDVI_clim_max)
        NDVI_clim_max = X;
    else
        m = isfinite(X) & (~isfinite(NDVI_clim_max) | X > NDVI_clim_max);
        NDVI_clim_max(m) = X(m);
    end
end

end
function sf_row = build_sf_row_daily(vwc_row, ndvi_clim_row, ndvi_clim_max_row, ndvi_clim_min_row, cls_row, mode_sf)

vwc_row           = double(vwc_row(:)).';
ndvi_clim_row     = double(ndvi_clim_row(:)).';
ndvi_clim_max_row = double(ndvi_clim_max_row(:)).';
ndvi_clim_min_row = double(ndvi_clim_min_row(:)).';
cls_row           = double(cls_row(:)).';

sf_row = nan(size(vwc_row));

% ===== 叶片项：始终用当天 NDVI_clim =====
vwc_leaf = 1.9134 .* (ndvi_clim_row.^2) - 0.3215 .* ndvi_clim_row;

% ===== 灌木/枝干项 =====
vwc_wood = vwc_row - vwc_leaf;

is_crop_grass = (cls_row == 10) | (cls_row == 12);
is_other      = ~is_crop_grass;
is_other(cls_row == 0) = false;

den = nan(size(vwc_row));
mode_sf = upper(string(mode_sf));

switch mode_sf
    case "POINT1"
        % 草地/农田：当天 NDVI_clim
        den(is_crop_grass) = (ndvi_clim_row(is_crop_grass) - 0.1) ./ 0.9;

        % 其他地类：NDVI_clim 年最大值
        den(is_other) = (ndvi_clim_max_row(is_other) - 0.1) ./ 0.9;

    case "NDVIMIN"
        % 草地/农田：(NDVI_day - NDVI_clim_min)/(1 - NDVI_clim_min)
        den(is_crop_grass) = ...
            (ndvi_clim_row(is_crop_grass) - ndvi_clim_min_row(is_crop_grass)) ./ ...
            (1 - ndvi_clim_min_row(is_crop_grass));

        % 其他地类：(NDVI_clim_max - NDVI_clim_min)/(1 - NDVI_clim_min)
        den(is_other) = ...
            (ndvi_clim_max_row(is_other) - ndvi_clim_min_row(is_other)) ./ ...
            (1 - ndvi_clim_min_row(is_other));

    otherwise
        error('未知 CFG.SF_INVERT_MODE=%s', string(mode_sf));
end

sf_row = vwc_wood ./ den;

% ===== 基本 QC =====
bad = false(size(sf_row));
bad = bad | ~isfinite(vwc_row);
bad = bad | ~isfinite(ndvi_clim_row);
bad = bad | ~isfinite(ndvi_clim_max_row);
bad = bad | ~isfinite(ndvi_clim_min_row);
bad = bad | ~isfinite(den);
bad = bad | (den <= 0);
bad = bad | ~isfinite(sf_row);
bad = bad | (sf_row < 0);
bad = bad | (cls_row == 0);

sf_row(bad) = nan;

end
function NDVI_DOY_CLIM = build_ndvi_doy_climatology_for_pixels(CFG, lin_pix)

Np = numel(lin_pix);
NDVI_sum = zeros(366, Np);
NDVI_cnt = zeros(366, Np);

L = dir(fullfile(CFG.ndvi_folder, '*.mat'));
if isempty(L)
    error('NDVI 文件夹为空：%s', CFG.ndvi_folder);
end

T = Get_date(L);
if isnumeric(T)
    T = datetime(T,'ConvertFrom','datenum');
end
T = dateshift(T(:),'start','day');

keep = year(T) >= CFG.ndvi_doy_clim_start_year & year(T) <= CFG.ndvi_doy_clim_end_year;
L = L(keep);
T = T(keep);

if isempty(L)
    error('指定年份范围内没有 NDVI 文件：%d-%d', ...
        CFG.ndvi_doy_clim_start_year, CFG.ndvi_doy_clim_end_year);
end

fprintf('[NDVI] DOY climatology 文件数 = %d\n', numel(L));

for k = 1:numel(L)
    if mod(k,30)==1 || k==numel(L)
        fprintf('[NDVI] DOY climatology %d / %d | %s\n', ...
            k, numel(L), datestr(T(k),'yyyy-mm-dd'));
    end

    f = fullfile(CFG.ndvi_folder, L(k).name);
    S = load(f, 'NDVI');
    if ~isfield(S,'NDVI')
        continue;
    end

    row = double(S.NDVI(lin_pix));
    row = row(:).';
    doy_k = day(T(k), 'dayofyear');

    ok = isfinite(row);
    NDVI_sum(doy_k, ok) = NDVI_sum(doy_k, ok) + row(ok);
    NDVI_cnt(doy_k, ok) = NDVI_cnt(doy_k, ok) + 1;
end

NDVI_DOY_CLIM = nan(366, Np);
ok = NDVI_cnt >= CFG.ndvi_doy_clim_min_count;
NDVI_DOY_CLIM(ok) = NDVI_sum(ok) ./ NDVI_cnt(ok);
end
function NDVI_clim_min = build_ndvi_clim_min(ndvi_clim_folder, varname)

NDVI_clim_min = [];

for doy = 1:366
    f = fullfile(ndvi_clim_folder, sprintf('%d.mat', doy));
    if exist(f,'file')~=2
        error('缺少 NDVI_clim 文件：%s', f);
    end

    S = load(f, varname);
    X = double(S.(varname));

    if isempty(NDVI_clim_min)
        NDVI_clim_min = X;
    else
        m = isfinite(X) & (~isfinite(NDVI_clim_min) | X < NDVI_clim_min);
        NDVI_clim_min(m) = X(m);
    end
end

end
