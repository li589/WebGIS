function OMEGA_AVG_DAILY_ONE_YEAR_FROM_RAW_BLOCK()
% =========================================================================
% 单年运行 avg 方案：
% 1) 若 avg omega DOY 库不存在，则先从 raw omega 构造；
% 2) 然后只跑 CFG.target_year 这一年；
% 3) TB/NDVI/SMref/Ts/GLDAS 的读取与预读逻辑，尽量保持和你现有
%    OMEGA_AVG_DAILY_FROM_RAW_BLOCK 的快逻辑一致。
%
% 说明：
% - 第一次跑某个方案时，会自动从多年 raw 结果构造 avg omega；
% - 之后再跑其他年份时，会直接复用已有的 avg omega DOY 文件；
% - h/alpha 仍然从该目标年的 raw R 中读取；
% - 年内日输入的预读方式沿用你原代码中的 preload_one_year_avg_inputs。
% =========================================================================

clc; warning('off','backtrace');

% ===== 主进程限制线程 + 底层库线程 =====
try, maxNumCompThreads(1); catch, end
setenv('OMP_NUM_THREADS','1');
setenv('MKL_NUM_THREADS','1');
setenv('OPENBLAS_NUM_THREADS','1');
setenv('VECLIB_MAXIMUM_THREADS','1');

tAll = tic;

%% =========================================================================
%% ============================== 配置区 ===================================
%% =========================================================================

% ---------------- 选择方案 ----------------
% 可选：
%   "FY_SINGLE"
%   "FY_DUAL"
%   "SMAP_SINGLE"
%   "SMAP_DUAL"
CFG.scheme = "FY_SINGLE";

% ---------------- 本次只跑这一年 ----------------
CFG.target_year = 2025;

% ---------------- avg omega 的多年构造时间范围 ----------------
% 只在第一次构造 avg omega 时使用
CFG.avg_build_start_date = '20150101';
CFG.avg_build_end_date   = '20251231';

% ---------------- 本次输出时间范围（自动按目标年） ----------------
CFG.start_date = sprintf('%04d0101', CFG.target_year);
CFG.end_date   = sprintf('%04d1231', CFG.target_year);

% ---------------- avg omega 的构造方式 ----------------
% "ALL_DAYS"   : 从 block_mat 读 8天块 omega，块内每天都赋同一个 omega，再做 DOY 平均
% "VALID_ONLY" : 从 R.OMEGA 读逐日 omega（只有原 raw 有值的日子才参与 DOY 平均）
CFG.avg_source_mode = "ALL_DAYS";

% ---------------- avg omega 在最终回代时的赋值方式 ----------------
% "ALL_DAYS"   : 当天只要回代所需量齐全且该 DOY 的 avg omega 有值，就直接回代
% "VALID_ONLY" : 只有当天 valid_tau 且该像元该日 avg omega 有值才回代
CFG.avg_apply_mode = "ALL_DAYS";

% ---------------- avg omega 是否自动构造 ----------------
CFG.auto_build_avg_if_missing = true;   % 若缺少 doy_001~366，则自动构造
CFG.force_rebuild_avg         = false;  % true 时强制重建 avg omega

% ===== NDVI 方案 =====
% "DAILY_FILE" | "DOY_CLIM"
CFG.NDVI_MODE = "DOY_CLIM";

CFG.ndvi_doy_clim_start_year = 2015;
CFG.ndvi_doy_clim_end_year   = 2025;
CFG.ndvi_doy_clim_min_count  = 1;

% ===== 静态 NDVI climatology：1.mat ~ 366.mat，变量 NDVI_clim =====
CFG.ndvi_clim_folder  = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/NDVI_clim/';
CFG.ndvi_clim_varname = 'NDVI_clim';

% ===== SF 方案 =====
% "STATIC" | "INVERTED_DAILY"
CFG.SF_MODE = "INVERTED_DAILY";

% "POINT1" | "NDVIMIN"
CFG.SF_INVERT_MODE = "POINT1";

% ===== Tau 的 VWC2 公式 =====
% "POINT1" | "NDVIMIN"
CFG.TAU_VWC2_MODE = "POINT1";

% ---------------- 输出 ----------------
CFG.out_root = '/public/home/chensf29/output/smap_single_avg_2point_sf';
CFG.out_daily = fullfile(CFG.out_root, 'daily_mat');      % 最终逐日 SM/VOD/OMEGA
CFG.out_aux   = fullfile(CFG.out_root, 'aux_data');       % 中间缓存
CFG.out_avgomega_doy = fullfile(CFG.out_aux, 'avg_omega_doy');
CFG.out_log_cache    = fullfile(CFG.out_aux, 'raw_omega_daily_cache');

% 是否覆盖已有 daily 输出
CFG.overwrite = true;

% ---------------- Function 路径 ----------------
CFG.func_dir = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAcode/2.Code/Function/';

% ---------------- 日输入数据路径 ----------------
CFG.smap_folder    = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAPdata/MAT/';
CFG.fy3d_folder    = '/public/shared_data/Chenhaojun/FY3D_output/matfinalfinal/';
CFG.fy3b_folder    = '/public/shared_data/Chenhaojun/FY3Bmat/';
CFG.ndvi_folder    = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/VNP13C1002/4.Daily/';
CFG.anc_root       = '/public/shared_data/Chenhaojun/DDCAfuxian/DDCAdata/SMAP_ancillary/';
CFG.gldas_mat_folder = '/share/home/user03/Chenhaojun/GLDASmat/';
CFG.gldas_template_file = '/share/home/user03/Chenhaojun/output/GLDAS_UTC_TEMPLATE/gldas_utc_template_global.mat';
CFG.USE_GLDAS_TEMPLATE = true;
CFG.ddca_sm_folder = '/share/home/user03/Chenhaojun/YH/SM/';

% ---------------- SM_SOURCE ----------------
CFG.SM_SOURCE = "SMAP";   % "SMAP" | "DDCA"

% ---------------- FY match ----------------
CFG.MATCH_ENABLE = true;
CFG.MATCH_METHOD = "bias";     % "none" | "bias" | "cdf"
CFG.match_fy3b_folder = CFG.fy3b_folder;
CFG.match_fy3d_folder = CFG.fy3d_folder;
CFG.match_start_date = '20190101';
CFG.match_end_date   = '20191231';
CFG.match_min_valid_n = 20;
CFG.MATCH_CDF_EXTRAP  = true;

% ---------------- 温度参数 ----------------
CFG.CT_SMREF = 0.30;
CFG.CT_EXP   = 0.30;

CFG.fy3d_desc_local_hour = 2.0;
CFG.fy3b_desc_local_hour = 1 + 40/60;
CFG.smap_desc_local_hour = 6.0;
CFG.gldas_time_tol_hours = 1.6;

CFG.gldas_var_TC     = 'Ts_gldas';
CFG.gldas_var_Tsoil1 = 'Tsoil1_gldas';
CFG.gldas_var_Tsoil2 = 'Tsoil2_gldas';
CFG.DUAL_TG_MODE     = "PAPER_CT";   % "PAPER_CT" | "TSOIL1_ONLY" | "TSOIL2_ONLY"

% ===== FY 坏点删除 =====
CFG.SPIKE.enable = true;
CFG.SPIKE.apply_to = "ALL";   % "FY" 或 "FY_ONLY" "SMAP""ALL""NONE"
CFG.SPIKE.default_TBv_thr = 25;
CFG.SPIKE.default_TBh_thr = 25;
CFG.SPIKE.station_keys    = strings(0,1);
CFG.SPIKE.station_TBv_thr = [];
CFG.SPIKE.station_TBh_thr = [];

% ---------------- 反演参数 ----------------
LAMBDA_TAU = 20;

% ---------------- 并行 ----------------
PAR.ENABLE      = true;
PAR.NUM_WORKERS = [];
PAR.MAX_WORKERS = inf;

% ---------------- 外层像元分块：控制"全年预读 + chunk 回代" ----------------
CFG.PIXEL_CHUNK_SIZE = 200000;
% 建议先用 200000；
% 若后面内存还高，再改 100000 或 50000

% ---------------- chunk 中间结果目录 ----------------
CFG.chunk_result_root = fullfile(CFG.out_aux, 'chunk_daily_result');

% ---------------- 原 raw 输出目录模板 ----------------
CFG.raw_root_pattern.FY_SINGLE_3B = '/public/shared_data/Chenhaojun/omega_final_0-1/fy3b_single_%d_2point_sf';
CFG.raw_root_pattern.FY_SINGLE_3D = '/public/shared_data/Chenhaojun/omega_final_0-1/fy_single_%d_2point_sf';

CFG.raw_root_pattern.FY_DUAL_3B   = '/public/shared_data/Chenhaojun/omega_final_0-1/fy3b_dual_%d_2point_sf';
CFG.raw_root_pattern.FY_DUAL_3D   = '/public/shared_data/Chenhaojun/omega_final_0-1/fy_dual_%d_2point_sf';

CFG.raw_root_pattern.SMAP_SINGLE  = '/public/shared_data/Chenhaojun/omega_final_0-1/smap_single_%d_2point_sf';
CFG.raw_root_pattern.SMAP_DUAL    = '/public/shared_data/Chenhaojun/omega_final_0-1/smap_dual_%d_2point_sf';

% ---------------- 打印节奏 ----------------
CFG.PRINT_EVERY_DAYS = 20;

% ---------------- 单/双温度由方案自动决定 ----------------
schemeU = upper(string(CFG.scheme));
if contains(schemeU, "DUAL")
    CFG.TEMP_SCHEME = "DUAL";
else
    CFG.TEMP_SCHEME = "ORIG_TS";
end

if startsWith(schemeU, "FY")
    CFG.TB_SOURCE = "FY";
else
    CFG.TB_SOURCE = "SMAP";
end

addpath(CFG.func_dir);

if ~exist(CFG.out_root,'dir'), mkdir(CFG.out_root); end
if ~exist(CFG.out_daily,'dir'), mkdir(CFG.out_daily); end
if ~exist(CFG.out_aux,'dir'), mkdir(CFG.out_aux); end
if ~exist(CFG.out_avgomega_doy,'dir'), mkdir(CFG.out_avgomega_doy); end
if ~exist(CFG.out_log_cache,'dir'), mkdir(CFG.out_log_cache); end
CFG.ndvi_cache_dir = fullfile(CFG.out_aux,'ndvi_cache');
if ~exist(CFG.ndvi_cache_dir,'dir'), mkdir(CFG.ndvi_cache_dir); end
if ~exist(CFG.chunk_result_root,'dir')
    mkdir(CFG.chunk_result_root);
end
fprintf('\n==================================================================\n');
fprintf('[START] OMEGA_AVG_DAILY_ONE_YEAR_FROM_RAW_BLOCK\n');
fprintf('[TIME ] %s\n', datestr(now,'yyyy-mm-dd HH:MM:SS'));
fprintf('[SCHEME] %s\n', char(CFG.scheme));
fprintf('[YEAR ] %d\n', CFG.target_year);
fprintf('[AVG  ] source_mode=%s | apply_mode=%s\n', char(CFG.avg_source_mode), char(CFG.avg_apply_mode));
fprintf('[TEMP ] TEMP_SCHEME=%s\n', char(CFG.TEMP_SCHEME));
fprintf('[TB   ] TB_SOURCE=%s\n', char(CFG.TB_SOURCE));
fprintf('[SM   ] SM_SOURCE=%s\n', char(CFG.SM_SOURCE));
fprintf('[AVG-RANGE] %s ~ %s\n', CFG.avg_build_start_date, CFG.avg_build_end_date);
fprintf('==================================================================\n');

print_scheme_read_paths(CFG);
CFG.PAR = PAR;

%% =========================================================================
%% ============================ 并行池 =====================================
%% =========================================================================
[usePar, pool] = setup_parpool(PAR);
if usePar
    fprintf('[PAR ] 并行池：%d workers\n', pool.NumWorkers);
else
    fprintf('[PAR ] 串行运行。\n');
end

%% =========================================================================
%% ============================ 静态库 =====================================
%% =========================================================================
fprintf('[INIT] 读取静态库 ...\n');

S = load(fullfile(CFG.anc_root,'IGBP_9km_12.mat'));
assert(isfield(S,'IGBP_9km_12'), 'IGBP_9km_12.mat 缺少 IGBP_9km_12');
LC      = S.IGBP_9km_12;
lat_9km = pick_field(S,'lat_9km');
lon_9km = pick_field(S,'lon_9km');

SB   = load(fullfile(CFG.anc_root,'B.mat'));      B      = SB.B;
SSF  = load(fullfile(CFG.anc_root,'SF.mat'));     SF     = SSF.SF_smap;
Sbd  = load(fullfile(CFG.anc_root,'BD.mat'));     BD     = Sbd.BD;
Scf  = load(fullfile(CFG.anc_root,'CF.mat'));     CF     = Scf.CF;

Smm = load('/public/shared_data/Chenhaojun/FYdata/VNP13C1002/5.MM/daily/1525/VI_v_qa.mat', ...
    'NDVI_v_max','NDVI_v_min');
NDVI_v_max = Smm.NDVI_v_max;
NDVI_v_min = Smm.NDVI_v_min;
NDVI_clim_max = build_ndvi_clim_max(CFG.ndvi_clim_folder, CFG.ndvi_clim_varname);
NDVI_clim_min = build_ndvi_clim_min(CFG.ndvi_clim_folder, CFG.ndvi_clim_varname);

[nrow, ncol] = size(LC);
fprintf('[INIT] Grid size = %d x %d\n', nrow, ncol);

%% =========================================================================
%% ============================ GLDAS 索引 =================================
%% =========================================================================
GLDAS_INDEX = struct('files',[],'t_utc',NaT(0,1));
GLDAS_TEMPLATE = struct();
GLDAS_DAY_SLOT = struct();

if upper(string(CFG.TEMP_SCHEME))=="DUAL"
    fprintf('[GLDAS] 建立 GLDAS 索引 ...\n');
    GLDAS_INDEX = build_gldas_file_index(CFG.gldas_mat_folder);

    if isfield(CFG,'USE_GLDAS_TEMPLATE') && CFG.USE_GLDAS_TEMPLATE
        fprintf('[GLDAS] 读取 GLDAS template ...\n');
        Sg = load(CFG.gldas_template_file);

        if upper(string(CFG.TB_SOURCE))=="FY"
            GLDAS_TEMPLATE = Sg;
        else
            GLDAS_TEMPLATE = Sg.SMAP_template;
        end

        GLDAS_DAY_SLOT = build_gldas_day_slot_table(GLDAS_INDEX);
    end
end

%% =========================================================================
%% ====================== 先检查 / 构造 avg omega ==========================
%% =========================================================================
avg_ready = avg_omega_library_ready(CFG);

if CFG.force_rebuild_avg || ~avg_ready
    if ~CFG.auto_build_avg_if_missing
        error('avg omega DOY 文件缺失，但 CFG.auto_build_avg_if_missing=false。');
    end

    fprintf('\n[A+B] avg omega DOY 库不存在或要求重建，开始从 raw 结果构造 ...\n');

    years_all = year(datetime(CFG.avg_build_start_date,'InputFormat','yyyyMMdd')) : ...
                year(datetime(CFG.avg_build_end_date,'InputFormat','yyyyMMdd'));

    fprintf('\n[A] 开始构造 raw omega 逐日缓存 ...\n');
    if usePar
    parfor iyear = 1:numel(years_all)
        yy_now = years_all(iyear);
        build_one_year_raw_daily_omega_cache(CFG, yy_now, LC);
    end
else
    for iyear = 1:numel(years_all)
        yy_now = years_all(iyear);
        build_one_year_raw_daily_omega_cache(CFG, yy_now, LC);
    end
end
    fprintf('[A] raw omega 逐日缓存完成。\n');

    fprintf('\n[B] 开始构造 DOY 平均 omega ...\n');
    build_avg_omega_doy_files(CFG, LC, years_all, false);
    fprintf('[B] DOY 平均 omega 完成。\n');

else
    fprintf('\n[A+B] 检测到 avg omega DOY 已存在，直接复用。\n');
end


%% =========================================================================
%% ====================== C：读取目标年 h/alpha map ========================
%% =========================================================================
yy = CFG.target_year;

fprintf('\n[C] 读取目标年 h/alpha 来源 ...\n');
infoY = resolve_year_scheme_info(CFG, yy);
if ~infoY.exists
    error('[C][YEAR %d] raw 年目录不存在。', yy);
end

fprintf('[C][YEAR %d] raw_root = %s\n', yy, infoY.raw_root);
fprintf('[C][YEAR %d] mat      = %s\n', yy, infoY.mat_dir);
fprintf('[C][YEAR %d] block    = %s\n', yy, infoY.block_dir);

[h_map, alpha_map, ok_halpha] = build_halpha_map_from_year_R(infoY.mat_dir, LC);
if ~ok_halpha
    error('[C][YEAR %d] h/alpha map 构建失败。', yy);
end
fprintf('[C][YEAR %d] h/alpha 来源: %s\n', yy, infoY.mat_dir);

%% =========================================================================
%% ======================= D：只跑目标年逐日回代 ===========================
%% =========================================================================
fprintf('\n[D] 开始目标年逐日回代 SM / VOD ...\n');

t_req = datetime(CFG.start_date,'InputFormat','yyyyMMdd') : ...
        datetime(CFG.end_date,'InputFormat','yyyyMMdd');

T_smap = get_dates_from_folder(CFG.smap_folder);

if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"
    T_ndvi = get_dates_from_folder(CFG.ndvi_folder);
else
    T_ndvi = t_req;   % DOY_CLIM 模式下，不要求当天 NDVI 文件存在
end

if upper(string(CFG.TB_SOURCE))=="FY"
    if upper(string(infoY.fy_platform))=="3B"
        T_tb = get_dates_from_folder(CFG.fy3b_folder);
    else
        T_tb = get_dates_from_folder(CFG.fy3d_folder);
    end
else
    T_tb = T_smap;
end

if upper(string(CFG.SM_SOURCE))=="DDCA"
    T_smref = get_dates_from_folder(CFG.ddca_sm_folder);
elseif upper(string(CFG.SM_SOURCE))=="SMAP"
    T_smref = T_smap;
else
    T_smref = t_req;
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

T_base = intersect(t_req, T_tb);
T_base = intersect(T_base, T_ndvi);
T_base = intersect(T_base, T_smref);

if need_smap_file
    T_base = intersect(T_base, T_smap);
end

if upper(string(CFG.TEMP_SCHEME))=="DUAL"
    T_gldas_day = unique(dateshift(GLDAS_INDEX.t_utc,'start','day'));
    T_base = intersect(T_base, T_gldas_day);
end

t_year = dateshift(T_base,'start','day');

if isempty(t_year)
    error('目标年可用日期交集为空，请检查 TB/NDVI/SMref 以及（DUAL时）GLDAS 数据。');
end

fprintf('[D] 目标年可用日期：%d（%s ~ %s）\n', ...
    numel(t_year), datestr(t_year(1),'yyyy-mm-dd'), datestr(t_year(end),'yyyy-mm-dd'));
out_year_dir = fullfile(CFG.out_daily, sprintf('%04d', yy));
if ~exist(out_year_dir,'dir'), mkdir(out_year_dir); end

%% =========================================================================
%% =================== D2：按像元 chunk 预读 + 回代 ========================
%% =========================================================================

lin_pix = (1:numel(LC)).';
Npix_all = numel(lin_pix);
Nday = numel(t_year);

%% ==================== NDVI DOY climatology 缓存准备 ====================
% 保持原来的缓存文件名、变量名不变；
% 只是缓存存在时，不再整体 load，而是后面按 chunk 局部读取。

NDVI_DOY_CLIM_FILE = [];
ndvi_cache_file = '';

if upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    pix_hash  = sum(double(lin_pix(:)));
    pix_first = double(lin_pix(1));
    pix_last  = double(lin_pix(end));

    ndvi_cache_file = fullfile(CFG.ndvi_cache_dir, sprintf( ...
        'NDVI_DOY_CLIM_%d_%d_Npix%d_F%u_L%u_H%.0f.mat', ...
        CFG.ndvi_doy_clim_start_year, CFG.ndvi_doy_clim_end_year, ...
        numel(lin_pix), pix_first, pix_last, pix_hash));

    if exist(ndvi_cache_file, 'file') == 2
        fprintf('[NDVI] 检测到 DOY climatology 缓存，后续按 chunk 局部读取：%s\n', ...
            ndvi_cache_file);
    else
        fprintf('[NDVI] 开始构建 DOY climatology: %d-%d\n', ...
            CFG.ndvi_doy_clim_start_year, CFG.ndvi_doy_clim_end_year);

        NDVI_DOY_CLIM = build_ndvi_doy_climatology_for_pixels(CFG, lin_pix);

        save(ndvi_cache_file, 'NDVI_DOY_CLIM', '-v7.3');
        fprintf('[NDVI] DOY climatology 已保存：%s\n', ndvi_cache_file);

        clear NDVI_DOY_CLIM
    end

    NDVI_DOY_CLIM_FILE = matfile(ndvi_cache_file);
end

%% ==================== 外层像元 chunk 配置 ====================
chunk_size = CFG.PIXEL_CHUNK_SIZE;
nChunk = ceil(Npix_all / chunk_size);

fprintf('[CHUNK] 启用 avg 回代像元分块：CHUNK_SIZE=%d | nChunk=%d | 总像元=%d\n', ...
    chunk_size, nChunk, Npix_all);

chunk_year_dir = fullfile(CFG.chunk_result_root, sprintf('%04d', yy));
if ~exist(chunk_year_dir,'dir')
    mkdir(chunk_year_dir);
end

%% ========================================================================
%% ==================== 外层：逐 chunk 预读 + 逐日回代 =====================
%% ========================================================================

for ic = 1:nChunk

    i1 = (ic-1)*chunk_size + 1;
    i2 = min(ic*chunk_size, Npix_all);

    idx_chunk = i1:i2;
    lin_pix_chunk = lin_pix(idx_chunk);
    Nc = numel(lin_pix_chunk);

    fprintf('\n============================================================\n');
    fprintf('[CHUNK] %d / %d | 像元序号 %d ~ %d | 当前像元数=%d\n', ...
        ic, nChunk, i1, i2, Nc);
    fprintf('============================================================\n');

    %% -------- 当前 chunk 的 NDVI DOY climatology --------
    NDVI_DOY_CLIM_chunk = [];

    if upper(string(CFG.NDVI_MODE))=="DOY_CLIM"
        fprintf('[NDVI][CHUNK %d/%d] 读取 DOY climatology 列 %d ~ %d\n', ...
            ic, nChunk, i1, i2);

        NDVI_DOY_CLIM_chunk = NDVI_DOY_CLIM_FILE.NDVI_DOY_CLIM(:, idx_chunk);
    end

    %% -------- 当前 chunk 的 avg omega 年序列 --------
    fprintf('[AVGOMEGA][CHUNK %d/%d] 读取当前 chunk 的 avg omega ...\n', ic, nChunk);

    OMEGA_AVG_chunk = preload_avg_omega_chunk(CFG, t_year, lin_pix_chunk);

    fprintf('[AVGOMEGA][CHUNK %d/%d] 完成。\n', ic, nChunk);

    %% -------- 当前 chunk 的全年输入预读 --------
    fprintf('[PRELOAD][CHUNK %d/%d] 开始预读全年输入 ...\n', ic, nChunk);

    YEAR_chunk = preload_one_year_avg_inputs_chunk( ...
        t_year, CFG, infoY, ...
        LC, lat_9km, lon_9km, ...
        lin_pix_chunk, ...
        NDVI_clim_max, NDVI_clim_min, NDVI_DOY_CLIM_chunk, ...
        GLDAS_INDEX, GLDAS_TEMPLATE, GLDAS_DAY_SLOT, ...
        false);

    fprintf('[PRELOAD][CHUNK %d/%d] 完成。\n', ic, nChunk);

    %% -------- 当前 chunk 做全年 TB 坏点删除 --------
    YEAR_chunk = apply_spike_cleaning_one_year(YEAR_chunk, CFG, usePar);

    %% -------- 当前 chunk 的全年回代结果容器 --------
    SM_chunk    = nan(Nday, Nc, 'single');
    VOD_chunk   = nan(Nday, Nc, 'single');
    OMEGA_chunk = nan(Nday, Nc, 'single');

    %% -------- 当前 chunk 内逐日回代 --------
    for k = 1:Nday

        day_dt = t_year(k);

        if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nday
            fprintf('[D][CHUNK %d/%d][YEAR %d] %4d / %4d | %s\n', ...
                ic, nChunk, yy, k, Nday, datestr(day_dt,'yyyy-mm-dd'));
        end

        [OK, DAILY_chunk] = process_one_day_from_preloaded_chunk( ...
            k, t_year, YEAR_chunk, CFG, OMEGA_AVG_chunk, ...
            LC(lin_pix_chunk), ...
            B(lin_pix_chunk), ...
            BD(lin_pix_chunk), ...
            CF(lin_pix_chunk), ...
            NDVI_v_max(lin_pix_chunk), ...
            NDVI_v_min(lin_pix_chunk), ...
            h_map(lin_pix_chunk), ...
            alpha_map(lin_pix_chunk), ...
            LAMBDA_TAU, usePar);

        if ~OK
            fprintf('[MISS][CHUNK %d/%d] %s 输入不齐，该 chunk 保持 NaN 占位。\n', ...
                ic, nChunk, datestr(day_dt,'yyyymmdd'));
        end

        SM_chunk(k,:)    = DAILY_chunk.SM(:).';
        VOD_chunk(k,:)   = DAILY_chunk.VOD(:).';
        OMEGA_chunk(k,:) = DAILY_chunk.OMEGA(:).';
    end

    %% -------- 保存当前 chunk 年度结果 --------
    chunk_file = fullfile(chunk_year_dir, sprintf('chunk_%04d.mat', ic));

    save(chunk_file, ...
        'lin_pix_chunk', 'SM_chunk', 'VOD_chunk', 'OMEGA_chunk', 't_year', ...
        '-v7.3');

    fprintf('[CHUNK] %d / %d 已保存：%s\n', ic, nChunk, chunk_file);

    %% -------- 释放当前 chunk 的大变量 --------
    clear YEAR_chunk NDVI_DOY_CLIM_chunk OMEGA_AVG_chunk
    clear SM_chunk VOD_chunk OMEGA_chunk
end

%% ========================================================================
%% ==================== 最后拼回原来的逐日 daily_mat =======================
%% ========================================================================

fprintf('\n[MERGE] 所有 chunk 完成，开始恢复原来的逐日 SM/VOD/OMEGA 文件 ...\n');

for k = 1:Nday

    day_dt = t_year(k);
    name = datestr(day_dt,'yyyymmdd');
    out_file = fullfile(out_year_dir, [name '.mat']);

    if exist(out_file,'file')==2 && ~CFG.overwrite
        fprintf('[SKIP] 已存在: %s\n', out_file);
        continue;
    end

    SM_vec    = nan(Npix_all,1,'single');
    VOD_vec   = nan(Npix_all,1,'single');
    OMEGA_vec = nan(Npix_all,1,'single');

    for ic = 1:nChunk

        chunk_file = fullfile(chunk_year_dir, sprintf('chunk_%04d.mat', ic));

        if exist(chunk_file,'file')~=2
            error('[MERGE] 缺少 chunk 文件：%s', chunk_file);
        end

        M = matfile(chunk_file);

        pix_chunk = M.lin_pix_chunk;
        SM_row    = M.SM_chunk(k,:);
        VOD_row   = M.VOD_chunk(k,:);
        OMEGA_row = M.OMEGA_chunk(k,:);

        SM_vec(pix_chunk)    = SM_row(:);
        VOD_vec(pix_chunk)   = VOD_row(:);
        OMEGA_vec(pix_chunk) = OMEGA_row(:);
    end

    SM    = reshape(SM_vec,    size(LC)); %#ok<NASGU>
    VOD   = reshape(VOD_vec,   size(LC)); %#ok<NASGU>
    OMEGA = reshape(OMEGA_vec, size(LC)); %#ok<NASGU>
    date_str = name; %#ok<NASGU>

    save(out_file, 'SM', 'VOD', 'OMEGA', 'date_str', '-v7.3');

    if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nday
        fprintf('[MERGE][YEAR %d] %4d / %4d | 已保存 %s\n', ...
            yy, k, Nday, out_file);
    end
end
fprintf('\n[DONE] 目标年 %d 完成，总耗时 %.1fs\n', yy, toc(tAll));
end
%% =========================================================================
%% ======================= avg omega 是否已就绪 ============================
%% =========================================================================
function tf = avg_omega_library_ready(CFG)
tf = true;
for doy_now = 1:366
    f_avg = fullfile(CFG.out_avgomega_doy, sprintf('doy_%03d.mat', doy_now));
    if exist(f_avg,'file')~=2
        tf = false;
        return;
    end
end
end

%% =========================================================================
%% ==================== 阶段A：每年 raw omega 日缓存 =======================
%% =========================================================================
function build_one_year_raw_daily_omega_cache(CFG, yy, LC)

infoY = resolve_year_scheme_info(CFG, yy);
if ~infoY.exists
    fprintf('[A][YEAR %d] 找不到 raw 年目录，跳过。\n', yy);
    return;
end

cache_year_dir = fullfile(CFG.out_log_cache, sprintf('%04d', yy));
if ~exist(cache_year_dir,'dir'), mkdir(cache_year_dir); end

fprintf('[A][YEAR %d] 构造逐日 raw omega 缓存 ...\n', yy);
fprintf('[A][YEAR %d] raw_root = %s\n', yy, infoY.raw_root);
fprintf('[A][YEAR %d] mode     = %s\n', yy, char(CFG.avg_source_mode));

switch upper(string(CFG.avg_source_mode))
    case "ALL_DAYS"
        Lb = dir(fullfile(infoY.block_dir, '*.mat'));
        if isempty(Lb)
            fprintf('[A][YEAR %d] block_mat 为空，跳过。\n', yy);
            return;
        end

        for i = 1:numel(Lb)
            f = fullfile(Lb(i).folder, Lb(i).name);
            S = load(f, 'OMEGA_grid', 'date_start', 'date_end');

            if ~isfield(S,'OMEGA_grid')
                continue;
            end

            d0 = datetime(string(S.date_start), 'InputFormat','yyyyMMdd');
            d1 = datetime(string(S.date_end),   'InputFormat','yyyyMMdd');

            if year(d0) ~= yy
                d0 = max(d0, datetime(yy,1,1));
                d1 = min(d1, datetime(yy,12,31));
            end

            for dt = d0:d1
                name = datestr(dt,'yyyymmdd');
                fout = fullfile(cache_year_dir, [name '.mat']);

                OMEGA_daily = S.OMEGA_grid; %#ok<NASGU>
                save(fout, 'OMEGA_daily', '-v7.3');
            end
        end

    case "VALID_ONLY"
        [okR, R] = load_year_R(infoY.mat_dir);
        if ~okR
            fprintf('[A][YEAR %d] 找不到 R，跳过。\n', yy);
            return;
        end

        [~,~,Nd] = year_date_info(yy);
        t_year = datetime(yy,1,1) : datetime(yy,12,31);

        fprintf('[A][YEAR %d] 从 R.OMEGA 构造 VALID_ONLY 逐日缓存 ...\n', yy);
        fprintf('[A][YEAR %d] 像元记录数 = %d\n', yy, numel(R));

        for k = 1:Nd
            dt = t_year(k);
            name = datestr(dt,'yyyymmdd');
            fout = fullfile(cache_year_dir, [name '.mat']);

            OMEGA_daily = nan(size(LC), 'single');

            for i = 1:numel(R)
                if isempty(R(i)), continue; end
                if ~isfield(R(i),'iy') || ~isfield(R(i),'ix') || ~isfield(R(i),'tvec') || ~isfield(R(i),'OMEGA')
                    continue;
                end
                iy = double(R(i).iy);
                ix = double(R(i).ix);
                if ~(iy>=1 && iy<=size(LC,1) && ix>=1 && ix<=size(LC,2))
                    continue;
                end

                tv = R(i).tvec(:);
                [tf, loc] = ismember(dt, tv);
                if tf && loc>=1 && loc<=numel(R(i).OMEGA) && isfinite(R(i).OMEGA(loc))
                    OMEGA_daily(iy,ix) = single(R(i).OMEGA(loc));
                end
            end

            save(fout, 'OMEGA_daily', '-v7.3');

            if mod(k,30)==1 || k==Nd
                fprintf('[A][YEAR %d] VALID_ONLY %4d / %4d | %s\n', yy, k, Nd, datestr(dt,'yyyy-mm-dd'));
            end
        end

    otherwise
        error('未知 CFG.avg_source_mode=%s', string(CFG.avg_source_mode));
end

fprintf('[A][YEAR %d] 逐日 raw omega 缓存完成。\n', yy);
end

%% =========================================================================
%% ======================= 阶段B：构造 DOY 平均 omega ======================
%% =========================================================================
  function build_avg_omega_doy_files(CFG, LC, years_all, usePar)

[nrow, ncol] = size(LC);

out_avgomega_doy = CFG.out_avgomega_doy;
out_log_cache    = CFG.out_log_cache;

if usePar
    parfor doy_now = 1:366
        fout = fullfile(out_avgomega_doy, sprintf('doy_%03d.mat', doy_now));

        sum_grid   = zeros(nrow, ncol, 'single');
        count_grid = zeros(nrow, ncol, 'uint16');
        used_years = 0;

        for iyear = 1:numel(years_all)
            yy = years_all(iyear);
            dt = datetime(yy,1,1) + days(doy_now-1);

            if year(dt) ~= yy
                continue;
            end

            fin = fullfile(out_log_cache, sprintf('%04d',yy), [datestr(dt,'yyyymmdd') '.mat']);
            if exist(fin, 'file') ~= 2
                continue;
            end

            S = load(fin, 'OMEGA_daily');
            if ~isfield(S, 'OMEGA_daily')
                continue;
            end

            X = single(S.OMEGA_daily);
            ok = isfinite(X);

            sum_grid(ok)   = sum_grid(ok) + X(ok);
            count_grid(ok) = count_grid(ok) + 1;
            used_years = used_years + 1;
        end

        OMEGA_AVG = nan(nrow, ncol, 'single');
        okc = count_grid > 0;
        OMEGA_AVG(okc) = sum_grid(okc) ./ single(count_grid(okc));

        save(fout, 'OMEGA_AVG', 'count_grid', 'used_years', '-v7.3');
    end

    for doy_now = 1:366
        if mod(doy_now,20)==1 || doy_now==366
            fprintf('[B][PAR] DOY %3d / 366 done\n', doy_now);
        end
    end

else
    for doy_now = 1:366
        fout = fullfile(out_avgomega_doy, sprintf('doy_%03d.mat', doy_now));

        sum_grid   = zeros(nrow, ncol, 'single');
        count_grid = zeros(nrow, ncol, 'uint16');
        used_years = 0;

        for iyear = 1:numel(years_all)
            yy = years_all(iyear);
            dt = datetime(yy,1,1) + days(doy_now-1);

            if year(dt) ~= yy
                continue;
            end

            fin = fullfile(out_log_cache, sprintf('%04d',yy), [datestr(dt,'yyyymmdd') '.mat']);
            if exist(fin, 'file') ~= 2
                continue;
            end

            S = load(fin, 'OMEGA_daily');
            if ~isfield(S, 'OMEGA_daily')
                continue;
            end

            X = single(S.OMEGA_daily);
            ok = isfinite(X);

            sum_grid(ok)   = sum_grid(ok) + X(ok);
            count_grid(ok) = count_grid(ok) + 1;
            used_years = used_years + 1;
        end

        OMEGA_AVG = nan(nrow, ncol, 'single');
        okc = count_grid > 0;
        OMEGA_AVG(okc) = sum_grid(okc) ./ single(count_grid(okc));

        save(fout, 'OMEGA_AVG', 'count_grid', 'used_years', '-v7.3');

        if mod(doy_now,20)==1 || doy_now==366
            fprintf('[B] DOY %3d / 366 | 有贡献年份次数=%d\n', doy_now, used_years);
        end
    end
end
end

%% =========================================================================
%% ==================== 从 yearly mat 中构造 h/alpha map ===================
%% =========================================================================
function [h_map, alpha_map, ok] = build_halpha_map_from_year_R(mat_dir, LC)

h_map = nan(size(LC), 'single');
alpha_map = nan(size(LC), 'single');
ok = false;

[okR, R] = load_year_R(mat_dir);
if ~okR
    return;
end

fprintf('[H/A] 从 R 构造 h / alpha map ...\n');
for i = 1:numel(R)
    if isempty(R(i)), continue; end
    if ~isfield(R(i),'iy') || ~isfield(R(i),'ix') || ~isfield(R(i),'inv_info')
        continue;
    end
    iy = double(R(i).iy);
    ix = double(R(i).ix);
    if ~(iy>=1 && iy<=size(LC,1) && ix>=1 && ix<=size(LC,2))
        continue;
    end

    if isfield(R(i).inv_info,'h_star') && isfinite(R(i).inv_info.h_star)
        h_map(iy,ix) = single(R(i).inv_info.h_star);
    end
    if isfield(R(i).inv_info,'alpha_star') && isfinite(R(i).inv_info.alpha_star)
        alpha_map(iy,ix) = single(R(i).inv_info.alpha_star);
    end
end

ok = any(isfinite(h_map(:))) && any(isfinite(alpha_map(:)));
fprintf('[H/A] finite h = %d | finite alpha = %d\n', nnz(isfinite(h_map)), nnz(isfinite(alpha_map)));
end

%% =========================================================================
%% ========================= 读取一年 R ====================================
%% =========================================================================
function [okR, R] = load_year_R(mat_dir)

okR = false;
R = [];

if exist(mat_dir,'dir')~=7
    return;
end

L = dir(fullfile(mat_dir, 'OMEGA_IDENT_exp0*.mat'));
if isempty(L)
    fprintf('[R   ] 未找到 exp0 文件: %s\n', mat_dir);
    return;
end

f = fullfile(L(1).folder, L(1).name);
fprintf('[R   ] 读取 exp0: %s\n', f);

S = load(f, 'R');

if isfield(S,'R')
    R = S.R;
    okR = true;
end
end

%% =========================================================================
%% ========================= 路径解析 ======================================
%% =========================================================================
function infoY = resolve_year_scheme_info(CFG, yy)

infoY = struct();
infoY.exists = false;
infoY.raw_root = '';
infoY.mat_dir = '';
infoY.block_dir = '';
infoY.fy_platform = "";

schemeU = upper(string(CFG.scheme));

switch schemeU
    case "FY_SINGLE"
        if yy <= 2018
            raw_root = sprintf(CFG.raw_root_pattern.FY_SINGLE_3B, yy);
            fy_platform = "3B";
        else
            raw_root = sprintf(CFG.raw_root_pattern.FY_SINGLE_3D, yy);
            fy_platform = "3D";
        end

    case "FY_DUAL"
        if yy <= 2018
            raw_root = sprintf(CFG.raw_root_pattern.FY_DUAL_3B, yy);
            fy_platform = "3B";
        else
            raw_root = sprintf(CFG.raw_root_pattern.FY_DUAL_3D, yy);
            fy_platform = "3D";
        end

    case "SMAP_SINGLE"
        raw_root = sprintf(CFG.raw_root_pattern.SMAP_SINGLE, yy);
        fy_platform = "";

    case "SMAP_DUAL"
        raw_root = sprintf(CFG.raw_root_pattern.SMAP_DUAL, yy);
        fy_platform = "";

    otherwise
        error('未知 CFG.scheme=%s', string(CFG.scheme));
end

infoY.raw_root = raw_root;
infoY.mat_dir = fullfile(raw_root, 'mat');
infoY.block_dir = fullfile(raw_root, 'block_mat');
infoY.fy_platform = fy_platform;

if exist(raw_root,'dir')==7 && exist(infoY.mat_dir,'dir')==7 && exist(infoY.block_dir,'dir')==7
    infoY.exists = true;
end
end

function print_scheme_read_paths(CFG)
fprintf('[PATH ] 方案读取规则：\n');
switch upper(string(CFG.scheme))
    case "FY_SINGLE"
        fprintf('        FY_SINGLE: 2015-2018 -> FY3B raw 年目录\n');
        fprintf('                  2019-2025 -> FY3D raw 年目录\n');
        fprintf('        3B 日 TB 会做 match；3D 不做\n');
    case "FY_DUAL"
        fprintf('        FY_DUAL  : 2015-2018 -> FY3B raw 年目录\n');
        fprintf('                  2019-2025 -> FY3D raw 年目录\n');
        fprintf('        3B 日 TB 会做 match；3D 不做\n');
    case "SMAP_SINGLE"
        fprintf('        SMAP_SINGLE: 各年读取 SMAP raw 年目录\n');
    case "SMAP_DUAL"
        fprintf('        SMAP_DUAL  : 各年读取 SMAP raw 年目录\n');
end
end

%% =========================================================================
%% ======================== 读单日 GLDAS ===================================
%% =========================================================================
function [TC, Tsoil1, Tsoil2, okTemp] = read_one_day_gldas_fields( ...
    day_dt, CFG, lat_9km, lon_9km, use_fy_platform, GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT)

TC = nan(size(lat_9km));
Tsoil1 = nan(size(lat_9km));
Tsoil2 = nan(size(lat_9km));
okTemp = false;

[nrow, ncol] = size(lat_9km);
lin_pix = (1:numel(lat_9km)).';
lon_use = lon_9km(:);

if isfield(CFG,'USE_GLDAS_TEMPLATE') && CFG.USE_GLDAS_TEMPLATE
    if upper(string(CFG.TB_SOURCE))=="FY"
        if upper(string(use_fy_platform))=="3B"
            GLDAS_TEMPLATE = GLDAS_TEMPLATE_ALL.FY3B_template;
        elseif upper(string(use_fy_platform))=="3D"
            GLDAS_TEMPLATE = GLDAS_TEMPLATE_ALL.FY3D_template;
        else
            error('未知 FY 平台');
        end
    else
        GLDAS_TEMPLATE = GLDAS_TEMPLATE_ALL;
    end

    slot_idx_all   = nan(numel(lin_pix),1);
    day_offset_all = nan(numel(lin_pix),1);

    for s = 1:numel(lin_pix)
        iy = ceil(s / ncol);
        ix = s - (iy-1)*ncol;
        slot_idx_all(s)   = double(GLDAS_TEMPLATE.slot_index(iy,ix));
        day_offset_all(s) = double(GLDAS_TEMPLATE.slot_day_offset(iy,ix));
    end

    m_prev = isfinite(slot_idx_all) & (day_offset_all == -1);
    m_curr = isfinite(slot_idx_all) & (day_offset_all == 0);
    m_next = isfinite(slot_idx_all) & (day_offset_all == 1);

    pix_prev = find(m_prev); slot_prev = slot_idx_all(pix_prev);
    pix_curr = find(m_curr); slot_curr = slot_idx_all(pix_curr);
    pix_next = find(m_next); slot_next = slot_idx_all(pix_next);

    row_prev = find(GLDAS_DAY_SLOT.days == dateshift(day_dt,'start','day') - days(1), 1, 'first');
    row_curr = find(GLDAS_DAY_SLOT.days == dateshift(day_dt,'start','day'),           1, 'first');
    row_next = find(GLDAS_DAY_SLOT.days == dateshift(day_dt,'start','day') + days(1), 1, 'first');

    gidx_all = nan(numel(lin_pix),1);

    if ~isempty(row_prev)
        idx_prev = GLDAS_DAY_SLOT.gidx_mat(row_prev,:);
        okp = slot_prev>=1 & slot_prev<=numel(idx_prev);
        gidx_all(pix_prev(okp)) = idx_prev(slot_prev(okp));
    end
    if ~isempty(row_curr)
        idx_curr = GLDAS_DAY_SLOT.gidx_mat(row_curr,:);
        okc = slot_curr>=1 & slot_curr<=numel(idx_curr);
        gidx_all(pix_curr(okc)) = idx_curr(slot_curr(okc));
    end
    if ~isempty(row_next)
        idx_next = GLDAS_DAY_SLOT.gidx_mat(row_next,:);
        okn = slot_next>=1 & slot_next<=numel(idx_next);
        gidx_all(pix_next(okn)) = idx_next(slot_next(okn));
    end

    uidx = unique(gidx_all(isfinite(gidx_all)));
    if isempty(uidx)
        return;
    end

    TCv = nan(numel(lin_pix),1);
    T1v = nan(numel(lin_pix),1);
    T2v = nan(numel(lin_pix),1);

    for uu = 1:numel(uidx)
        ig = uidx(uu);
        ss = find(gidx_all == ig);

        G = load(fullfile(CFG.gldas_mat_folder, GLDAS_INDEX.files(ig).name), ...
            CFG.gldas_var_TC, CFG.gldas_var_Tsoil1, CFG.gldas_var_Tsoil2);

        TC_grid     = double(G.(CFG.gldas_var_TC));
        Tsoil1_grid = double(G.(CFG.gldas_var_Tsoil1));
        Tsoil2_grid = double(G.(CFG.gldas_var_Tsoil2));

        TCv(ss) = TC_grid(lin_pix(ss));
        T1v(ss) = Tsoil1_grid(lin_pix(ss));
        T2v(ss) = Tsoil2_grid(lin_pix(ss));
    end

    TC     = reshape(TCv, nrow, ncol);
    Tsoil1 = reshape(T1v, nrow, ncol);
    Tsoil2 = reshape(T2v, nrow, ncol);
    okTemp = true;

else
    if upper(string(CFG.TB_SOURCE))=="FY"
        if upper(string(use_fy_platform))=="3D"
            local_hour_now = CFG.fy3d_desc_local_hour;
        else
            local_hour_now = CFG.fy3b_desc_local_hour;
        end
    else
        local_hour_now = CFG.smap_desc_local_hour;
    end

    target_utc = local_overpass_to_utc_vec(day_dt, lon_use, local_hour_now);
    idx_pick = pick_gldas_file_indices(GLDAS_INDEX.t_utc, target_utc, CFG.gldas_time_tol_hours);
    uidx = unique(idx_pick(isfinite(idx_pick)));
    if isempty(uidx)
        return;
    end

    TCv = nan(numel(lin_pix),1);
    T1v = nan(numel(lin_pix),1);
    T2v = nan(numel(lin_pix),1);

    for uu = 1:numel(uidx)
        ig = uidx(uu);
        ss = find(idx_pick == ig);

        G = load(fullfile(CFG.gldas_mat_folder, GLDAS_INDEX.files(ig).name), ...
            CFG.gldas_var_TC, CFG.gldas_var_Tsoil1, CFG.gldas_var_Tsoil2);

        TC_grid     = double(G.(CFG.gldas_var_TC));
        Tsoil1_grid = double(G.(CFG.gldas_var_Tsoil1));
        Tsoil2_grid = double(G.(CFG.gldas_var_Tsoil2));

        TCv(ss) = TC_grid(lin_pix(ss));
        T1v(ss) = Tsoil1_grid(lin_pix(ss));
        T2v(ss) = Tsoil2_grid(lin_pix(ss));
    end

    TC     = reshape(TCv, nrow, ncol);
    Tsoil1 = reshape(T1v, nrow, ncol);
    Tsoil2 = reshape(T2v, nrow, ncol);
    okTemp = true;
end
end

%% =========================================================================
%% =========================== 年日期辅助 ==================================
%% =========================================================================
function [isLeap, daysInYear, Nd] = year_date_info(yy)
isLeap = (mod(yy,4)==0 && mod(yy,100)~=0) || mod(yy,400)==0;
if isLeap
    daysInYear = 366;
else
    daysInYear = 365;
end
Nd = daysInYear;
end

%% =========================================================================
%% ========================== 与原代码一致的函数 ============================
%% =========================================================================
function freq_GHz = pick_freq_GHz(CFG)
freq_GHz = 1.41;
if upper(string(CFG.TB_SOURCE))=="FY"
    freq_GHz = 10.65;
end
end

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

function [SM,VOD] = DDCA_single_temp(TBv,TBh,Ts,Tau_ini,h,CF,omega,porosity,Freq,Theta,alpha,LAMBDA_TAU)

TBv        = double(TBv);
TBh        = double(TBh);
Ts         = double(Ts);
Tau_ini    = double(Tau_ini);
h          = double(h);
CF         = double(CF);
omega      = double(omega);
porosity   = double(porosity);
Freq       = double(Freq);
Theta      = double(Theta);
alpha      = double(alpha);
LAMBDA_TAU = double(LAMBDA_TAU);

opts = optimoptions('lsqnonlin','Display','off', ...
    'MaxIterations',400, ...
    'FunctionTolerance',1e-6, ...
    'StepTolerance',1e-6);

fun = @(x) F_sm_single_temp(x,TBv,TBh,Ts,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU);

x0 = double([0.20; Tau_ini]);
lb = double([0.02; 0]);
ub = double([porosity; 5]);

xhat = lsqnonlin(fun, x0, lb, ub, opts);

SM  = real(double(xhat(1)));
VOD = real(double(xhat(2)));
end

function [SM,VOD] = DDCA_dual_temp(TBv,TBh,TC,TG,Tau_ini,h,CF,omega,porosity,Freq,Theta,alpha,LAMBDA_TAU)

TBv        = double(TBv);
TBh        = double(TBh);
TC         = double(TC);
TG         = double(TG);
Tau_ini    = double(Tau_ini);
h          = double(h);
CF         = double(CF);
omega      = double(omega);
porosity   = double(porosity);
Freq       = double(Freq);
Theta      = double(Theta);
alpha      = double(alpha);
LAMBDA_TAU = double(LAMBDA_TAU);

opts = optimoptions('lsqnonlin','Display','off', ...
    'MaxIterations',400, ...
    'FunctionTolerance',1e-6, ...
    'StepTolerance',1e-6);

fun = @(x) F_sm_dual_temp(x,TBv,TBh,TC,TG,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU);

x0 = double([0.20; Tau_ini]);
lb = double([0.02; 0]);
ub = double([porosity; 5]);

xhat = lsqnonlin(fun, x0, lb, ub, opts);

SM  = real(double(xhat(1)));
VOD = real(double(xhat(2)));
end

function Func = F_sm_single_temp(x,TBv,TBh,Ts,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU)

x          = double(x);
TBv        = double(TBv);
TBh        = double(TBh);
Ts         = double(Ts);
Tau_ini    = double(Tau_ini);
h          = double(h);
CF         = double(CF);
omega      = double(omega);
Freq       = double(Freq);
Theta      = double(Theta);
alpha      = double(alpha);
LAMBDA_TAU = double(LAMBDA_TAU);

SM  = double(x(1));
Tau = double(x(2));

epsv = Mironov(Freq,SM,CF);
[rh, rv] = Fresnel(Theta, epsv);

rh = double(rh);
rv = double(rv);

Q     = max(alpha.*h,0);
atten = exp(-h.*cosd(Theta).^2);

rh_r = ((1-Q).*rh + Q.*rv).*atten;
rv_r = ((1-Q).*rv + Q.*rh).*atten;
gamma = exp(-Tau);

Tbv_m = Ts.*((1-rv_r).*gamma + (1-omega).*(1-gamma).*(1+rv_r.*gamma));
Tbh_m = Ts.*((1-rh_r).*gamma + (1-omega).*(1-gamma).*(1+rh_r.*gamma));

Func = double([Tbv_m-TBv; Tbh_m-TBh; LAMBDA_TAU.*(Tau-Tau_ini)]);
end

function Func = F_sm_dual_temp(x,TBv,TBh,TC,TG,Tau_ini,h,CF,omega,Freq,Theta,alpha,LAMBDA_TAU)

x          = double(x);
TBv        = double(TBv);
TBh        = double(TBh);
TC         = double(TC);
TG         = double(TG);
Tau_ini    = double(Tau_ini);
h          = double(h);
CF         = double(CF);
omega      = double(omega);
Freq       = double(Freq);
Theta      = double(Theta);
alpha      = double(alpha);
LAMBDA_TAU = double(LAMBDA_TAU);

SM  = double(x(1));
Tau = double(x(2));

epsv = Mironov(Freq,SM,CF);
[rh, rv] = Fresnel(Theta, epsv);

rh = double(rh);
rv = double(rv);

Q     = max(alpha.*h,0);
atten = exp(-h.*cosd(Theta).^2);

rh_r = ((1-Q).*rh + Q.*rv).*atten;
rv_r = ((1-Q).*rv + Q.*rh).*atten;
gamma = exp(-Tau);

Tbv_m = TG.*((1-rv_r).*gamma) + TC.*((1-omega).*(1-gamma).*(1+rv_r.*gamma));
Tbh_m = TG.*((1-rh_r).*gamma) + TC.*((1-omega).*(1-gamma).*(1+rh_r.*gamma));

Func = double([Tbv_m-TBv; Tbh_m-TBh; LAMBDA_TAU.*(Tau-Tau_ini)]);
end

function Tau_ini = Tau(NDVI, NDVI_max, NDVI_min, Landcover, b, sf, theta, mode_vwc2)

NDVI(NDVI<0 | NDVI>1) = nan;

[m,n] = size(NDVI); %#ok<ASGLU>
VWC2 = zeros(m,n);

VWC1 = 1.9134*(NDVI.^2) - 0.3215*NDVI;

mode_vwc2 = upper(string(mode_vwc2));

is_crop_grass = (Landcover == 10) | (Landcover == 12);
is_other      = ~is_crop_grass;
is_other(Landcover==0) = false;

switch mode_vwc2
    case "NDVIMIN"

        VWC2(is_crop_grass) = ...
            sf(is_crop_grass) ./ (1 - NDVI_min(is_crop_grass)) .* ...
            (NDVI(is_crop_grass) - NDVI_min(is_crop_grass));

        VWC2(is_other) = ...
            sf(is_other) ./ (1 - NDVI_min(is_other)) .* ...
            (NDVI_max(is_other) - NDVI_min(is_other));

    case "POINT1"

        den_crop = (NDVI(is_crop_grass) - 0.1) ./ 0.9;
        VWC2(is_crop_grass) = sf(is_crop_grass) .* den_crop;

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

function MATCH = build_match_models_for_pixels(CFG, lin_pix)

Np = numel(lin_pix);

t_req = datetime(CFG.match_start_date,'InputFormat','yyyyMMdd') : ...
        datetime(CFG.match_end_date,'InputFormat','yyyyMMdd');

T_b = get_dates_from_folder(CFG.match_fy3b_folder);
T_d = get_dates_from_folder(CFG.match_fy3d_folder);

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
    if mod(k,20)==1 || k==Nt
        fprintf('[MATCH] 读取训练样本 %d / %d | %s\n', k, Nt, datestr(t_train(k),'yyyy-mm-dd'));
    end
    name = datestr(t_train(k), 'yyyymmdd');
    fb = fullfile(CFG.match_fy3b_folder, [name '.mat']);
    fd = fullfile(CFG.match_fy3d_folder, [name '.mat']);

    Sb = load(fb, 'TBv', 'TBh');
    Sd = load(fd, 'TBv', 'TBh');

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
x = x_row(:);
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
end

x_adj = reshape(x_adj, orig_size);
end

function v = pick_field(S, name)
if isfield(S, name)
    v = S.(name);
else
    v = [];
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
try
    pctRunOnAll setenv('OMP_NUM_THREADS','1');
    pctRunOnAll setenv('MKL_NUM_THREADS','1');
    pctRunOnAll setenv('OPENBLAS_NUM_THREADS','1');
    pctRunOnAll setenv('VECLIB_MAXIMUM_THREADS','1');
catch
end
usePar = ~isempty(pool);
end

function nw = auto_detect_workers()
nw = str2double(getenv('SLURM_CPUS_PER_TASK'));
if ~(isfinite(nw) && nw>=1)
    try, nw = feature('numcores'); catch, nw = 4; end
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
    if ~isfinite(x(k))
        continue;
    end

    iL = k - 1;
    while iL >= 1 && ~isfinite(x(iL))
        iL = iL - 1;
    end

    iR = k + 1;
    while iR <= n && ~isfinite(x(iR))
        iR = iR + 1;
    end

    if iL < 1 || iR > n
        continue;
    end

    d1 = x(k) - x(iL);
    d2 = x(k) - x(iR);

    if abs(d1) >= thr && abs(d2) >= thr && sign(d1) == sign(d2)
        bad(k) = true;
    end
end

x_clean(bad) = NaN;
end

    function YEAR = preload_one_year_avg_inputs( ...
    t_year, CFG, infoY, ...
    LC, lat_9km, lon_9km, ...
    NDVI_clim_max, NDVI_clim_min, NDVI_DOY_CLIM, ...
    GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT, ...
    usePar)

Nt = numel(t_year);
nrow = size(LC,1);
ncol = size(LC,2);
Npix = numel(LC);
lin_pix = (1:Npix).';

YEAR = struct();
YEAR.t_year = t_year(:);
YEAR.sz = [nrow, ncol];

MATCH = [];
if upper(string(CFG.TB_SOURCE))=="FY" && upper(string(infoY.fy_platform))=="3B" ...
        && CFG.MATCH_ENABLE && upper(string(CFG.MATCH_METHOD))~="NONE"
    fprintf('[D][PRELOAD] 训练 FY3B->FY3D 匹配模型...\n');
    MATCH = build_match_models_for_pixels(CFG, lin_pix);
    fprintf('[D][PRELOAD] FY3B->FY3D 匹配模型完成。\n');
end

TBv_mat   = nan(Nt, Npix);
TBh_mat   = nan(Nt, Npix);
IA_mat    = nan(Nt, Npix);
NDVI_mat  = nan(Nt, Npix);
SMref_mat = nan(Nt, Npix);
SF_mat    = nan(Nt, Npix);

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    Ts_mat     = nan(Nt, Npix);
    TC_mat     = [];
    Tsoil1_mat = [];
    Tsoil2_mat = [];
else
    Ts_mat     = [];
    TC_mat     = nan(Nt, Npix);
    Tsoil1_mat = nan(Nt, Npix);
    Tsoil2_mat = nan(Nt, Npix);
end

if usePar
    parfor k = 1:Nt
        day_dt = t_year(k);
        name = datestr(day_dt,'yyyymmdd');

        TBv_row    = nan(1, Npix);
        TBh_row    = nan(1, Npix);
        IA_row     = nan(1, Npix);
        NDVI_row   = nan(1, Npix);
        SMref_row  = nan(1, Npix);
        Ts_row     = nan(1, Npix);
        TC_row     = nan(1, Npix);
        Tsoil1_row = nan(1, Npix);
        Tsoil2_row = nan(1, Npix);
        SF_row = nan(1, Npix);

        if upper(string(CFG.TB_SOURCE))=="FY"
            if upper(string(infoY.fy_platform))=="3B"
                f_tb = fullfile(CFG.fy3b_folder, [name '.mat']);
            else
                f_tb = fullfile(CFG.fy3d_folder, [name '.mat']);
            end
        else
            f_tb = fullfile(CFG.smap_folder, [name '.mat']);
        end

        f_sp   = fullfile(CFG.smap_folder, [name '.mat']);
        f_ndvi = fullfile(CFG.ndvi_folder, [name '.mat']);

        need_ndvi_file = upper(string(CFG.NDVI_MODE))=="DAILY_FILE";

if exist(f_tb,'file')~=2 || (need_ndvi_file && exist(f_ndvi,'file')~=2)
            if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
                fprintf('[D][PRELOAD][PAR] %4d / %4d | %s | missing TB/NDVI\n', ...
                    k, Nt, datestr(day_dt,'yyyy-mm-dd'));
            end
            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;

        end

        need_smap_file = upper(string(CFG.SM_SOURCE))=="SMAP" || ...
                 upper(string(CFG.TEMP_SCHEME))=="ORIG_TS" || ...
                 upper(string(CFG.SF_MODE))=="INVERTED_DAILY";
        if need_smap_file && exist(f_sp,'file')~=2
            if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
                fprintf('[D][PRELOAD][PAR] %4d / %4d | %s | missing SMAP\n', ...
                    k, Nt, datestr(day_dt,'yyyy-mm-dd'));
            end
            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;
        end

        if upper(string(CFG.SM_SOURCE))=="DDCA"
            f_ddca = fullfile(CFG.ddca_sm_folder, [name '.mat']);
            if exist(f_ddca,'file')~=2
                if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
                    fprintf('[D][PRELOAD][PAR] %4d / %4d | %s | missing DDCA\n', ...
                        k, Nt, datestr(day_dt,'yyyy-mm-dd'));
                end
                TBv_mat(k,:)   = TBv_row;
                TBh_mat(k,:)   = TBh_row;
                IA_mat(k,:)    = IA_row;
                NDVI_mat(k,:)  = NDVI_row;
                SMref_mat(k,:) = SMref_row;
                SF_mat(k,:)    = SF_row;

                if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                    Ts_mat(k,:) = Ts_row;
                else
                    TC_mat(k,:)     = TC_row;
                    Tsoil1_mat(k,:) = Tsoil1_row;
                    Tsoil2_mat(k,:) = Tsoil2_row;
                end
                continue;
            end
        else
            f_ddca = '';
        end

        if upper(string(CFG.TB_SOURCE))=="FY"
            Sfy = load(f_tb, 'TBv','TBh','IA');

            if isfield(Sfy,'TBv'), TBv_row = double(Sfy.TBv(lin_pix)); end
            if isfield(Sfy,'TBh'), TBh_row = double(Sfy.TBh(lin_pix)); end

            if isfield(Sfy,'IA')
                tmp = double(Sfy.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end

            if upper(string(infoY.fy_platform))=="3B" && ~isempty(MATCH)
                TBv_row = apply_match_row(TBv_row, MATCH.V, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
                TBh_row = apply_match_row(TBh_row, MATCH.H, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
            end
        else
            Ssp_tb = load(f_tb, 'TBv','TBh','IA');

            if isfield(Ssp_tb,'TBv'), TBv_row = double(Ssp_tb.TBv(lin_pix)); end
            if isfield(Ssp_tb,'TBh'), TBh_row = double(Ssp_tb.TBh(lin_pix)); end

            if isfield(Ssp_tb,'IA')
                tmp = double(Ssp_tb.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end
        end

        if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"

    Svi = load(f_ndvi, 'NDVI');
    if isfield(Svi,'NDVI')
        NDVI_row = double(Svi.NDVI(lin_pix));
    end

elseif upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    doy_k = day(day_dt,'dayofyear');

    if ~isempty(NDVI_DOY_CLIM)
        if size(NDVI_DOY_CLIM,1) ~= 366 || size(NDVI_DOY_CLIM,2) ~= Npix
            error('NDVI_DOY_CLIM 尺寸不匹配：期望 [366 x %d]，实际 [%d x %d]', ...
                Npix, size(NDVI_DOY_CLIM,1), size(NDVI_DOY_CLIM,2));
        end
        NDVI_row = double(NDVI_DOY_CLIM(doy_k,:));
    end

else
    error('未知 CFG.NDVI_MODE=%s', string(CFG.NDVI_MODE));
end
        % ===== SF：静态 or 基于 SMAP vwc + NDVI_clim 逐日反推 =====
        if upper(string(CFG.SF_MODE))=="STATIC"

            SSF_local = load(fullfile(CFG.anc_root,'SF.mat'));
            SF_static_local = SSF_local.SF_smap;
            SF_row = double(SF_static_local(lin_pix));

        elseif upper(string(CFG.SF_MODE))=="INVERTED_DAILY"

            doy_k = day(day_dt,'dayofyear');
            f_clim = fullfile(CFG.ndvi_clim_folder, sprintf('%d.mat', doy_k));

          if exist(f_clim,'file')~=2
    error('缺少 NDVI_clim 文件：%s', f_clim);
end
            Sclim = load(f_clim, CFG.ndvi_clim_varname);
            NDVI_clim_grid = Sclim.(CFG.ndvi_clim_varname);
            NDVI_clim_row  = double(NDVI_clim_grid(lin_pix));

            Svwc = load(f_sp, 'vwc');
            if ~isfield(Svwc, 'vwc')
                error('SMAP 日文件缺少变量 vwc：%s', f_sp);
            end

            vwc_row = double(Svwc.vwc(lin_pix));

            SF_row = build_sf_row_daily( ...
                vwc_row, ...
                NDVI_clim_row, ...
                NDVI_clim_max(lin_pix), ...
                NDVI_clim_min(lin_pix), ...
                LC(lin_pix), ...
                CFG.SF_INVERT_MODE);

        else
            error('未知 CFG.SF_MODE=%s', string(CFG.SF_MODE));
        end
        if upper(string(CFG.SM_SOURCE))=="SMAP"
            Ssm = load(f_sp, 'sm_dca');
            if isfield(Ssm,'sm_dca')
                SMref_row = double(Ssm.sm_dca(lin_pix));
            end
        else
            Sdd = load(f_ddca, 'SM');
            if isfield(Sdd,'SM')
                SMref_row = double(Sdd.SM(lin_pix));
            end
        end
        SMref_row(SMref_row<-0.01 | SMref_row>1.0) = NaN;

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            Ssp = load(f_sp, 'Ts');
            if isfield(Ssp,'Ts') && ~isempty(Ssp.Ts)
                Ts_row = double(Ssp.Ts(lin_pix));
            end
        else
            [TC, Tsoil1, Tsoil2, okTemp] = read_one_day_gldas_fields( ...
                day_dt, CFG, lat_9km, lon_9km, string(infoY.fy_platform), ...
                GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT);

            if okTemp
                TC_row     = double(TC(lin_pix));
                Tsoil1_row = double(Tsoil1(lin_pix));
                Tsoil2_row = double(Tsoil2(lin_pix));
            end
        end

        TBv_mat(k,:)   = TBv_row;
        TBh_mat(k,:)   = TBh_row;
        IA_mat(k,:)    = IA_row;
        NDVI_mat(k,:)  = NDVI_row;
        SMref_mat(k,:) = SMref_row;
        SF_mat(k,:)    = SF_row;

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            Ts_mat(k,:) = Ts_row;
        else
            TC_mat(k,:)     = TC_row;
            Tsoil1_mat(k,:) = Tsoil1_row;
            Tsoil2_mat(k,:) = Tsoil2_row;
        end
        if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
            fprintf('[D][PRELOAD][PAR] %4d / %4d | %s\n', k, Nt, datestr(day_dt,'yyyy-mm-dd'));
        end
    end
else
    for k = 1:Nt
        day_dt = t_year(k);
        name = datestr(day_dt,'yyyymmdd');

        if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
            fprintf('[D][PRELOAD] %4d / %4d | %s\n', k, Nt, datestr(day_dt,'yyyy-mm-dd'));
        end

        TBv_row    = nan(1, Npix);
        TBh_row    = nan(1, Npix);
        IA_row     = nan(1, Npix);
        NDVI_row   = nan(1, Npix);
        SMref_row  = nan(1, Npix);
        Ts_row     = nan(1, Npix);
        TC_row     = nan(1, Npix);
        Tsoil1_row = nan(1, Npix);
        Tsoil2_row = nan(1, Npix);
        SF_row     = nan(1, Npix);

        if upper(string(CFG.TB_SOURCE))=="FY"
            if upper(string(infoY.fy_platform))=="3B"
                f_tb = fullfile(CFG.fy3b_folder, [name '.mat']);
            else
                f_tb = fullfile(CFG.fy3d_folder, [name '.mat']);
            end
        else
            f_tb = fullfile(CFG.smap_folder, [name '.mat']);
        end

        f_sp   = fullfile(CFG.smap_folder, [name '.mat']);
        f_ndvi = fullfile(CFG.ndvi_folder, [name '.mat']);

        need_ndvi_file = upper(string(CFG.NDVI_MODE))=="DAILY_FILE";

        if exist(f_tb,'file')~=2 || (need_ndvi_file && exist(f_ndvi,'file')~=2)
            fprintf('[MISS][TB/NDVI] %s\n', datestr(day_dt,'yyyy-mm-dd'));

            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;
        end

        need_smap_file = upper(string(CFG.SM_SOURCE))=="SMAP" || ...
                         upper(string(CFG.TEMP_SCHEME))=="ORIG_TS" || ...
                         upper(string(CFG.SF_MODE))=="INVERTED_DAILY";

        if need_smap_file && exist(f_sp,'file')~=2
            fprintf('[MISS][SMAP] %s\n', f_sp);

            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;
        end

        if upper(string(CFG.SM_SOURCE))=="DDCA"
            f_ddca = fullfile(CFG.ddca_sm_folder, [name '.mat']);
            if exist(f_ddca,'file')~=2
                fprintf('[MISS][DDCA] %s\n', f_ddca);

                TBv_mat(k,:)   = TBv_row;
                TBh_mat(k,:)   = TBh_row;
                IA_mat(k,:)    = IA_row;
                NDVI_mat(k,:)  = NDVI_row;
                SMref_mat(k,:) = SMref_row;
                SF_mat(k,:)    = SF_row;

                if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                    Ts_mat(k,:) = Ts_row;
                else
                    TC_mat(k,:)     = TC_row;
                    Tsoil1_mat(k,:) = Tsoil1_row;
                    Tsoil2_mat(k,:) = Tsoil2_row;
                end
                continue;
            end
        else
            f_ddca = '';
        end

        % ===== TB / IA =====
        if upper(string(CFG.TB_SOURCE))=="FY"
            Sfy = load(f_tb, 'TBv','TBh','IA');

            if isfield(Sfy,'TBv')
                TBv_row = double(Sfy.TBv(lin_pix));
            end
            if isfield(Sfy,'TBh')
                TBh_row = double(Sfy.TBh(lin_pix));
            end
            if isfield(Sfy,'IA')
                tmp = double(Sfy.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end

            if upper(string(infoY.fy_platform))=="3B" && ~isempty(MATCH)
                TBv_row = apply_match_row(TBv_row, MATCH.V, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
                TBh_row = apply_match_row(TBh_row, MATCH.H, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
            end

        else
            Ssp_tb = load(f_tb, 'TBv','TBh','IA');

            if isfield(Ssp_tb,'TBv')
                TBv_row = double(Ssp_tb.TBv(lin_pix));
            end
            if isfield(Ssp_tb,'TBh')
                TBh_row = double(Ssp_tb.TBh(lin_pix));
            end
            if isfield(Ssp_tb,'IA')
                tmp = double(Ssp_tb.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end
        end

        % ===== NDVI：daily file or DOY climatology =====
        if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"

            Svi = load(f_ndvi, 'NDVI');
            if isfield(Svi,'NDVI')
                NDVI_row = double(Svi.NDVI(lin_pix));
            end

        elseif upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    doy_k = day(day_dt,'dayofyear');

    if ~isempty(NDVI_DOY_CLIM)
        if size(NDVI_DOY_CLIM,1) ~= 366 || size(NDVI_DOY_CLIM,2) ~= Npix
            error('NDVI_DOY_CLIM 尺寸不匹配：期望 [366 x %d]，实际 [%d x %d]', ...
                Npix, size(NDVI_DOY_CLIM,1), size(NDVI_DOY_CLIM,2));
        end
        NDVI_row = double(NDVI_DOY_CLIM(doy_k,:));
    end

        else
            error('未知 CFG.NDVI_MODE=%s', string(CFG.NDVI_MODE));
        end

        % ===== SF：STATIC or INVERTED_DAILY =====
        if upper(string(CFG.SF_MODE))=="STATIC"

            SSF_local = load(fullfile(CFG.anc_root,'SF.mat'));
            SF_static_local = SSF_local.SF_smap;
            SF_row = double(SF_static_local(lin_pix));

        elseif upper(string(CFG.SF_MODE))=="INVERTED_DAILY"

            doy_k = day(day_dt,'dayofyear');
            f_clim = fullfile(CFG.ndvi_clim_folder, sprintf('%d.mat', doy_k));

            if exist(f_clim,'file')~=2
    error('缺少 NDVI_clim 文件：%s', f_clim);
end

            Sclim = load(f_clim, CFG.ndvi_clim_varname);
            NDVI_clim_grid = Sclim.(CFG.ndvi_clim_varname);
            NDVI_clim_row  = double(NDVI_clim_grid(lin_pix));

            Svwc = load(f_sp, 'vwc');
            if ~isfield(Svwc, 'vwc')
                error('SMAP 日文件缺少变量 vwc：%s', f_sp);
            end

            vwc_row = double(Svwc.vwc(lin_pix));

            SF_row = build_sf_row_daily( ...
                vwc_row, ...
                NDVI_clim_row, ...
                NDVI_clim_max(lin_pix), ...
                NDVI_clim_min(lin_pix), ...
                LC(lin_pix), ...
                CFG.SF_INVERT_MODE);

        else
            error('未知 CFG.SF_MODE=%s', string(CFG.SF_MODE));
        end

        % ===== SMref =====
        if upper(string(CFG.SM_SOURCE))=="SMAP"
            Ssm = load(f_sp, 'sm_dca');
            if isfield(Ssm,'sm_dca')
                SMref_row = double(Ssm.sm_dca(lin_pix));
            end
        else
            Sdd = load(f_ddca, 'SM');
            if isfield(Sdd,'SM')
                SMref_row = double(Sdd.SM(lin_pix));
            end
        end
        SMref_row(SMref_row<-0.01 | SMref_row>1.0) = NaN;

        % ===== 温度 =====
        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

            Ssp = load(f_sp, 'Ts');
            if isfield(Ssp,'Ts') && ~isempty(Ssp.Ts)
                Ts_row = double(Ssp.Ts(lin_pix));
            end

        else
            [TC, Tsoil1, Tsoil2, okTemp] = read_one_day_gldas_fields( ...
                day_dt, CFG, lat_9km, lon_9km, string(infoY.fy_platform), ...
                GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT);

            if okTemp
                TC_row     = double(TC(lin_pix));
                Tsoil1_row = double(Tsoil1(lin_pix));
                Tsoil2_row = double(Tsoil2(lin_pix));
            end
        end

        TBv_mat(k,:)   = TBv_row;
        TBh_mat(k,:)   = TBh_row;
        IA_mat(k,:)    = IA_row;
        NDVI_mat(k,:)  = NDVI_row;
        SMref_mat(k,:) = SMref_row;
        SF_mat(k,:)    = SF_row;

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            Ts_mat(k,:) = Ts_row;
        else
            TC_mat(k,:)     = TC_row;
            Tsoil1_mat(k,:) = Tsoil1_row;
            Tsoil2_mat(k,:) = Tsoil2_row;
        end
    end
end

YEAR.TBv_mat   = TBv_mat;
YEAR.TBh_mat   = TBh_mat;
YEAR.IA_mat    = IA_mat;
YEAR.NDVI_mat  = NDVI_mat;
YEAR.SMref_mat = SMref_mat;
YEAR.SF_mat    = SF_mat;

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    YEAR.Ts_mat     = Ts_mat;
    YEAR.TC_mat     = [];
    YEAR.Tsoil1_mat = [];
    YEAR.Tsoil2_mat = [];
else
    YEAR.Ts_mat     = [];
    YEAR.TC_mat     = TC_mat;
    YEAR.Tsoil1_mat = Tsoil1_mat;
    YEAR.Tsoil2_mat = Tsoil2_mat;
end
end
function YEAR = apply_spike_cleaning_one_year(YEAR, CFG, usePar)

% 与代码1保持思路一致：
% 1) 先判断是否启用 SPIKE
% 2) 再根据 apply_to 和 TB_SOURCE 决定是否执行
% 3) 执行时按全年每个像元时间序列做 remove_isolated_spikes
% 4) usePar 由主程序传入，不再硬编码 false

if ~isfield(CFG,'SPIKE') || ~isstruct(CFG.SPIKE)
    return;
end
if ~isfield(CFG.SPIKE,'enable') || ~CFG.SPIKE.enable
    return;
end

tb_src = upper(string(CFG.TB_SOURCE));
mode_apply = "FY";
if isfield(CFG.SPIKE,'apply_to') && ~isempty(CFG.SPIKE.apply_to)
    mode_apply = upper(string(CFG.SPIKE.apply_to));
end

% 兼容你现在的 FY_ONLY，也兼容代码1原来的写法
switch mode_apply
    case {"FY","FY_ONLY"}
        do_spike = (tb_src == "FY");
    case "SMAP"
        do_spike = (tb_src == "SMAP");
    case "ALL"
        do_spike = (tb_src == "FY" || tb_src == "SMAP");
    case "NONE"
        do_spike = false;
    otherwise
        error('未知 CFG.SPIKE.apply_to=%s，允许值： "FY" | "FY_ONLY" | "SMAP" | "ALL" | "NONE"', ...
            string(CFG.SPIKE.apply_to));
end

if ~do_spike
    return;
end

fprintf('[D][SPIKE] 开始对整年 %s 时间序列做坏点删除...\n', char(tb_src));

[thr_v, thr_h] = get_station_spike_thresholds("", CFG);
[~, Npix] = size(YEAR.TBv_mat);

if usePar
    TBv_src = YEAR.TBv_mat;
    TBh_src = YEAR.TBh_mat;

    TBv_new = TBv_src;
    TBh_new = TBh_src;

    bad_v_cnt = zeros(1, Npix);
    bad_h_cnt = zeros(1, Npix);

    parfor s = 1:Npix
        [tbv_col, bad_v] = remove_isolated_spikes(TBv_src(:,s), thr_v);
        [tbh_col, bad_h] = remove_isolated_spikes(TBh_src(:,s), thr_h);

        TBv_new(:,s) = tbv_col;
        TBh_new(:,s) = tbh_col;
        bad_v_cnt(s) = nnz(bad_v);
        bad_h_cnt(s) = nnz(bad_h);
    end

    YEAR.TBv_mat = TBv_new;
    YEAR.TBh_mat = TBh_new;

    n_bad_v_sum = sum(bad_v_cnt);
    n_bad_h_sum = sum(bad_h_cnt);

else
    n_bad_v_sum = 0;
    n_bad_h_sum = 0;

    for s = 1:Npix
        [YEAR.TBv_mat(:,s), bad_v] = remove_isolated_spikes(YEAR.TBv_mat(:,s), thr_v);
        [YEAR.TBh_mat(:,s), bad_h] = remove_isolated_spikes(YEAR.TBh_mat(:,s), thr_h);

        n_bad_v_sum = n_bad_v_sum + nnz(bad_v);
        n_bad_h_sum = n_bad_h_sum + nnz(bad_h);
    end
end

fprintf('[D][SPIKE] 完成 | apply_to=%s | TBv bad=%d | TBh bad=%d | thrV=%.2f | thrH=%.2f\n', ...
    char(mode_apply), n_bad_v_sum, n_bad_h_sum, thr_v, thr_h);
end

function [OK, OUT] = process_one_day_from_preloaded_year( ...
    k, t_year, YEAR, CFG, AVG_OMEGA_CACHE, ...
    LC, B, BD, CF, NDVI_v_max, NDVI_v_min, ...
    h_map, alpha_map, LAMBDA_TAU, usePar)

OK = false;

nrow = size(LC,1);
ncol = size(LC,2);

OUT = struct();
OUT.SM    = nan(nrow,ncol,'single');
OUT.VOD   = nan(nrow,ncol,'single');
OUT.OMEGA = nan(nrow,ncol,'single');

day_dt = t_year(k);

doy_now = day(day_dt,'dayofyear');

if doy_now < 1 || doy_now > numel(AVG_OMEGA_CACHE) || isempty(AVG_OMEGA_CACHE{doy_now})
    fprintf('[MISS][AVGOMEGA] doy=%03d 不在缓存中\n', doy_now);
    return;
end

OMEGA_AVG = AVG_OMEGA_CACHE{doy_now};

TBv   = reshape(YEAR.TBv_mat(k,:),    nrow, ncol);
TBh   = reshape(YEAR.TBh_mat(k,:),    nrow, ncol);
IA    = reshape(YEAR.IA_mat(k,:),     nrow, ncol);
NDVI  = reshape(YEAR.NDVI_mat(k,:),   nrow, ncol);
SMref = reshape(YEAR.SMref_mat(k,:),  nrow, ncol);
SF_day = reshape(YEAR.SF_mat(k,:), nrow, ncol);
Ts     = nan(nrow,ncol);
TC     = nan(nrow,ncol);
Tsoil1 = nan(nrow,ncol);
Tsoil2 = nan(nrow,ncol);

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    Ts = reshape(YEAR.Ts_mat(k,:), nrow, ncol);
else
    TC     = reshape(YEAR.TC_mat(k,:),     nrow, ncol);
    Tsoil1 = reshape(YEAR.Tsoil1_mat(k,:), nrow, ncol);
    Tsoil2 = reshape(YEAR.Tsoil2_mat(k,:), nrow, ncol);
end

Tau_star = nan(size(TBv));
mask_tau_in = isfinite(NDVI) & isfinite(IA);
Tau_star(mask_tau_in) = Tau( ...
    NDVI(mask_tau_in), ...
    NDVI_v_max(mask_tau_in), ...
    NDVI_v_min(mask_tau_in), ...
    LC(mask_tau_in), ...
    B(mask_tau_in), ...
    SF_day(mask_tau_in), ...
    IA(mask_tau_in), ...
    CFG.TAU_VWC2_MODE);

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    valid_tau = isfinite(TBv) & isfinite(TBh) & isfinite(Ts) & ...
                isfinite(NDVI) & isfinite(IA) & ...
                isfinite(Tau_star) & isfinite(h_map) & isfinite(alpha_map);
else
    [~, TG] = build_effective_soil_temperature_scheme(SMref, Tsoil1, Tsoil2, CFG);
    valid_tau = isfinite(TBv) & isfinite(TBh) & isfinite(TC) & isfinite(TG) & ...
                isfinite(NDVI) & isfinite(IA) & ...
                isfinite(Tau_star) & isfinite(h_map) & isfinite(alpha_map);
end

if upper(string(CFG.avg_apply_mode))=="VALID_ONLY"
    mask_use = valid_tau & isfinite(OMEGA_AVG);
else
    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
        mask_use = isfinite(TBv) & isfinite(TBh) & isfinite(Ts) & ...
                   isfinite(IA) & isfinite(Tau_star) & ...
                   isfinite(h_map) & isfinite(alpha_map) & ...
                   isfinite(OMEGA_AVG);
    else
        mask_use = isfinite(TBv) & isfinite(TBh) & isfinite(TC) & isfinite(TG) & ...
                   isfinite(IA) & isfinite(Tau_star) & ...
                   isfinite(h_map) & isfinite(alpha_map) & ...
                   isfinite(OMEGA_AVG);
    end
end

if ~any(mask_use(:))
    OK = true;
    OUT.OMEGA = single(OMEGA_AVG);
    return;
end

OMEGA_USE = nan(size(OMEGA_AVG));
OMEGA_USE(mask_use) = OMEGA_AVG(mask_use);
OUT.OMEGA = single(OMEGA_USE);

porosity = 1 - BD ./ 2.65;
freq_GHz = pick_freq_GHz(CFG);
idx = find(mask_use);

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

    if usePar
        chunk_size = CFG.PAR.CHUNK_SIZE;
        nChunk = ceil(numel(idx) / chunk_size);

        IDX_buf = cell(nChunk,1);
        SM_buf  = cell(nChunk,1);
        VOD_buf = cell(nChunk,1);

        parfor ic = 1:nChunk
            i1 = (ic-1)*chunk_size + 1;
            i2 = min(ic*chunk_size, numel(idx));
            idx_sub = idx(i1:i2);

            sm_sub  = nan(numel(idx_sub),1,'single');
            vod_sub = nan(numel(idx_sub),1,'single');

            for j = 1:numel(idx_sub)
                p = idx_sub(j);
                [smi, vodi] = DDCA_single_temp( ...
                    TBv(p), TBh(p), Ts(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                    porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);
                sm_sub(j)  = single(smi);
                vod_sub(j) = single(vodi);
            end

            IDX_buf{ic} = idx_sub;
            SM_buf{ic}  = sm_sub;
            VOD_buf{ic} = vod_sub;
        end

        for ic = 1:nChunk
            OUT.SM(IDX_buf{ic})  = SM_buf{ic};
            OUT.VOD(IDX_buf{ic}) = VOD_buf{ic};
        end

    else
        for ii = 1:numel(idx)
            p = idx(ii);
            [smi, vodi] = DDCA_single_temp( ...
                TBv(p), TBh(p), Ts(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);
            OUT.SM(p)  = single(smi);
            OUT.VOD(p) = single(vodi);
        end
    end

else
    [~, TG] = build_effective_soil_temperature_scheme(SMref, Tsoil1, Tsoil2, CFG);

    if usePar
        chunk_size = CFG.PAR.CHUNK_SIZE;
        nChunk = ceil(numel(idx) / chunk_size);

        IDX_buf = cell(nChunk,1);
        SM_buf  = cell(nChunk,1);
        VOD_buf = cell(nChunk,1);

        parfor ic = 1:nChunk
            i1 = (ic-1)*chunk_size + 1;
            i2 = min(ic*chunk_size, numel(idx));
            idx_sub = idx(i1:i2);

            sm_sub  = nan(numel(idx_sub),1,'single');
            vod_sub = nan(numel(idx_sub),1,'single');

            for j = 1:numel(idx_sub)
                p = idx_sub(j);
                [smi, vodi] = DDCA_dual_temp( ...
                    TBv(p), TBh(p), TC(p), TG(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                    porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);
                sm_sub(j)  = single(smi);
                vod_sub(j) = single(vodi);
            end

            IDX_buf{ic} = idx_sub;
            SM_buf{ic}  = sm_sub;
            VOD_buf{ic} = vod_sub;
        end

        for ic = 1:nChunk
            OUT.SM(IDX_buf{ic})  = SM_buf{ic};
            OUT.VOD(IDX_buf{ic}) = VOD_buf{ic};
        end

    else
        for ii = 1:numel(idx)
            p = idx(ii);
            [smi, vodi] = DDCA_dual_temp( ...
                TBv(p), TBh(p), TC(p), TG(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);
            OUT.SM(p)  = single(smi);
            OUT.VOD(p) = single(vodi);
        end
    end
end

OK = true;
end

function AVG_OMEGA_CACHE = preload_avg_omega_cache(CFG)

AVG_OMEGA_CACHE = cell(366,1);

for doy_now = 1:366
    f_avg = fullfile(CFG.out_avgomega_doy, sprintf('doy_%03d.mat', doy_now));

    if exist(f_avg,'file')~=2
        AVG_OMEGA_CACHE{doy_now} = [];
        fprintf('[B2] 缺失 doy=%03d\n', doy_now);
        continue;
    end

    S = load(f_avg, 'OMEGA_AVG');

    if ~isfield(S, 'OMEGA_AVG')
        AVG_OMEGA_CACHE{doy_now} = [];
        fprintf('[B2] doy=%03d 文件缺少 OMEGA_AVG\n', doy_now);
        continue;
    end

    AVG_OMEGA_CACHE{doy_now} = double(S.OMEGA_AVG);

    if mod(doy_now,20)==1 || doy_now==366
        fprintf('[B2] %3d / 366\n', doy_now);
    end
end
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
function sf_row = build_sf_row_daily(vwc_row, ndvi_clim_row, ndvi_clim_max_row, ndvi_clim_min_row, cls_row, mode_sf)

vwc_row           = double(vwc_row(:)).';
ndvi_clim_row     = double(ndvi_clim_row(:)).';
ndvi_clim_max_row = double(ndvi_clim_max_row(:)).';
ndvi_clim_min_row = double(ndvi_clim_min_row(:)).';
cls_row           = double(cls_row(:)).';

sf_row = nan(size(vwc_row));

vwc_leaf = 1.9134 .* (ndvi_clim_row.^2) - 0.3215 .* ndvi_clim_row;
vwc_wood = vwc_row - vwc_leaf;

is_crop_grass = (cls_row == 10) | (cls_row == 12);
is_other      = ~is_crop_grass;
is_other(cls_row == 0) = false;

den = nan(size(vwc_row));
mode_sf = upper(string(mode_sf));

switch mode_sf
    case "POINT1"
        den(is_crop_grass) = (ndvi_clim_row(is_crop_grass) - 0.1) ./ 0.9;
        den(is_other)      = (ndvi_clim_max_row(is_other) - 0.1) ./ 0.9;

    case "NDVIMIN"
        den(is_crop_grass) = ...
            (ndvi_clim_row(is_crop_grass) - ndvi_clim_min_row(is_crop_grass)) ./ ...
            (1 - ndvi_clim_min_row(is_crop_grass));

        den(is_other) = ...
            (ndvi_clim_max_row(is_other) - ndvi_clim_min_row(is_other)) ./ ...
            (1 - ndvi_clim_min_row(is_other));

    otherwise
        error('未知 CFG.SF_INVERT_MODE=%s', string(mode_sf));
end

sf_row = vwc_wood ./ den;

bad = false(size(sf_row));
bad = bad | ~isfinite(vwc_row);
bad = bad | ~isfinite(ndvi_clim_row);
bad = bad | ~isfinite(ndvi_clim_max_row);
bad = bad | ~isfinite(ndvi_clim_min_row);
bad = bad | ~isfinite(den);
bad = bad | den <= 0;
bad = bad | ~isfinite(sf_row);
bad = bad | sf_row < 0;
bad = bad | cls_row == 0;

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
function OMEGA_AVG_chunk = preload_avg_omega_chunk(CFG, t_year, lin_pix_chunk)

Nday = numel(t_year);
Nc   = numel(lin_pix_chunk);

OMEGA_AVG_chunk = nan(Nday, Nc);

for k = 1:Nday

    day_dt = t_year(k);
    doy_now = day(day_dt, 'dayofyear');

    f_avg = fullfile(CFG.out_avgomega_doy, sprintf('doy_%03d.mat', doy_now));

    if exist(f_avg,'file')~=2
        fprintf('[AVGOMEGA][MISS] 缺少 doy=%03d 文件：%s\n', doy_now, f_avg);
        continue;
    end

    S = load(f_avg, 'OMEGA_AVG');

    if ~isfield(S,'OMEGA_AVG')
        fprintf('[AVGOMEGA][MISS] 文件缺少 OMEGA_AVG：%s\n', f_avg);
        continue;
    end

    OMEGA_grid = double(S.OMEGA_AVG);
    OMEGA_AVG_chunk(k,:) = OMEGA_grid(lin_pix_chunk);
end

end
function YEAR = preload_one_year_avg_inputs_chunk( ...
    t_year, CFG, infoY, ...
    LC, lat_9km, lon_9km, ...
    lin_pix, ...
    NDVI_clim_max, NDVI_clim_min, NDVI_DOY_CLIM, ...
    GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT, ...
    usePar)

Nt = numel(t_year);
nrow = size(LC,1);
ncol = size(LC,2);

lin_pix = lin_pix(:);
Npix = numel(lin_pix);

YEAR = struct();
YEAR.t_year = t_year(:);
YEAR.sz = [nrow, ncol];

MATCH = [];
if upper(string(CFG.TB_SOURCE))=="FY" && upper(string(infoY.fy_platform))=="3B" ...
        && CFG.MATCH_ENABLE && upper(string(CFG.MATCH_METHOD))~="NONE"
    fprintf('[D][PRELOAD] 训练 FY3B->FY3D 匹配模型...\n');
    MATCH = build_match_models_for_pixels(CFG, lin_pix);
    fprintf('[D][PRELOAD] FY3B->FY3D 匹配模型完成。\n');
end

TBv_mat   = nan(Nt, Npix);
TBh_mat   = nan(Nt, Npix);
IA_mat    = nan(Nt, Npix);
NDVI_mat  = nan(Nt, Npix);
SMref_mat = nan(Nt, Npix);
SF_mat    = nan(Nt, Npix);

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    Ts_mat     = nan(Nt, Npix);
    TC_mat     = [];
    Tsoil1_mat = [];
    Tsoil2_mat = [];
else
    Ts_mat     = [];
    TC_mat     = nan(Nt, Npix);
    Tsoil1_mat = nan(Nt, Npix);
    Tsoil2_mat = nan(Nt, Npix);
end

if usePar
    parfor k = 1:Nt
        day_dt = t_year(k);
        name = datestr(day_dt,'yyyymmdd');

        TBv_row    = nan(1, Npix);
        TBh_row    = nan(1, Npix);
        IA_row     = nan(1, Npix);
        NDVI_row   = nan(1, Npix);
        SMref_row  = nan(1, Npix);
        Ts_row     = nan(1, Npix);
        TC_row     = nan(1, Npix);
        Tsoil1_row = nan(1, Npix);
        Tsoil2_row = nan(1, Npix);
        SF_row = nan(1, Npix);

        if upper(string(CFG.TB_SOURCE))=="FY"
            if upper(string(infoY.fy_platform))=="3B"
                f_tb = fullfile(CFG.fy3b_folder, [name '.mat']);
            else
                f_tb = fullfile(CFG.fy3d_folder, [name '.mat']);
            end
        else
            f_tb = fullfile(CFG.smap_folder, [name '.mat']);
        end

        f_sp   = fullfile(CFG.smap_folder, [name '.mat']);
        f_ndvi = fullfile(CFG.ndvi_folder, [name '.mat']);

        need_ndvi_file = upper(string(CFG.NDVI_MODE))=="DAILY_FILE";

if exist(f_tb,'file')~=2 || (need_ndvi_file && exist(f_ndvi,'file')~=2)
            if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
                fprintf('[D][PRELOAD][PAR] %4d / %4d | %s | missing TB/NDVI\n', ...
                    k, Nt, datestr(day_dt,'yyyy-mm-dd'));
            end
            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;

        end

        need_smap_file = upper(string(CFG.SM_SOURCE))=="SMAP" || ...
                 upper(string(CFG.TEMP_SCHEME))=="ORIG_TS" || ...
                 upper(string(CFG.SF_MODE))=="INVERTED_DAILY";
        if need_smap_file && exist(f_sp,'file')~=2
            if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
                fprintf('[D][PRELOAD][PAR] %4d / %4d | %s | missing SMAP\n', ...
                    k, Nt, datestr(day_dt,'yyyy-mm-dd'));
            end
            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;
        end

        if upper(string(CFG.SM_SOURCE))=="DDCA"
            f_ddca = fullfile(CFG.ddca_sm_folder, [name '.mat']);
            if exist(f_ddca,'file')~=2
                if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
                    fprintf('[D][PRELOAD][PAR] %4d / %4d | %s | missing DDCA\n', ...
                        k, Nt, datestr(day_dt,'yyyy-mm-dd'));
                end
                TBv_mat(k,:)   = TBv_row;
                TBh_mat(k,:)   = TBh_row;
                IA_mat(k,:)    = IA_row;
                NDVI_mat(k,:)  = NDVI_row;
                SMref_mat(k,:) = SMref_row;
                SF_mat(k,:)    = SF_row;

                if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                    Ts_mat(k,:) = Ts_row;
                else
                    TC_mat(k,:)     = TC_row;
                    Tsoil1_mat(k,:) = Tsoil1_row;
                    Tsoil2_mat(k,:) = Tsoil2_row;
                end
                continue;
            end
        else
            f_ddca = '';
        end

        if upper(string(CFG.TB_SOURCE))=="FY"
            Sfy = load(f_tb, 'TBv','TBh','IA');

            if isfield(Sfy,'TBv'), TBv_row = double(Sfy.TBv(lin_pix)); end
            if isfield(Sfy,'TBh'), TBh_row = double(Sfy.TBh(lin_pix)); end

            if isfield(Sfy,'IA')
                tmp = double(Sfy.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end

            if upper(string(infoY.fy_platform))=="3B" && ~isempty(MATCH)
                TBv_row = apply_match_row(TBv_row, MATCH.V, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
                TBh_row = apply_match_row(TBh_row, MATCH.H, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
            end
        else
            Ssp_tb = load(f_tb, 'TBv','TBh','IA');

            if isfield(Ssp_tb,'TBv'), TBv_row = double(Ssp_tb.TBv(lin_pix)); end
            if isfield(Ssp_tb,'TBh'), TBh_row = double(Ssp_tb.TBh(lin_pix)); end

            if isfield(Ssp_tb,'IA')
                tmp = double(Ssp_tb.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end
        end

        if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"

    Svi = load(f_ndvi, 'NDVI');
    if isfield(Svi,'NDVI')
        NDVI_row = double(Svi.NDVI(lin_pix));
    end

elseif upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    doy_k = day(day_dt,'dayofyear');

    if ~isempty(NDVI_DOY_CLIM)
        if size(NDVI_DOY_CLIM,1) ~= 366 || size(NDVI_DOY_CLIM,2) ~= Npix
            error('NDVI_DOY_CLIM 尺寸不匹配：期望 [366 x %d]，实际 [%d x %d]', ...
                Npix, size(NDVI_DOY_CLIM,1), size(NDVI_DOY_CLIM,2));
        end
        NDVI_row = double(NDVI_DOY_CLIM(doy_k,:));
    end

else
    error('未知 CFG.NDVI_MODE=%s', string(CFG.NDVI_MODE));
end
        % ===== SF：静态 or 基于 SMAP vwc + NDVI_clim 逐日反推 =====
        if upper(string(CFG.SF_MODE))=="STATIC"

            SSF_local = load(fullfile(CFG.anc_root,'SF.mat'));
            SF_static_local = SSF_local.SF_smap;
            SF_row = double(SF_static_local(lin_pix));

        elseif upper(string(CFG.SF_MODE))=="INVERTED_DAILY"

            doy_k = day(day_dt,'dayofyear');
            f_clim = fullfile(CFG.ndvi_clim_folder, sprintf('%d.mat', doy_k));

          if exist(f_clim,'file')~=2
    error('缺少 NDVI_clim 文件：%s', f_clim);
end
            Sclim = load(f_clim, CFG.ndvi_clim_varname);
            NDVI_clim_grid = Sclim.(CFG.ndvi_clim_varname);
            NDVI_clim_row  = double(NDVI_clim_grid(lin_pix));

            Svwc = load(f_sp, 'vwc');
            if ~isfield(Svwc, 'vwc')
                error('SMAP 日文件缺少变量 vwc：%s', f_sp);
            end

            vwc_row = double(Svwc.vwc(lin_pix));

            SF_row = build_sf_row_daily( ...
                vwc_row, ...
                NDVI_clim_row, ...
                NDVI_clim_max(lin_pix), ...
                NDVI_clim_min(lin_pix), ...
                LC(lin_pix), ...
                CFG.SF_INVERT_MODE);

        else
            error('未知 CFG.SF_MODE=%s', string(CFG.SF_MODE));
        end
        if upper(string(CFG.SM_SOURCE))=="SMAP"
            Ssm = load(f_sp, 'sm_dca');
            if isfield(Ssm,'sm_dca')
                SMref_row = double(Ssm.sm_dca(lin_pix));
            end
        else
            Sdd = load(f_ddca, 'SM');
            if isfield(Sdd,'SM')
                SMref_row = double(Sdd.SM(lin_pix));
            end
        end
        SMref_row(SMref_row<-0.01 | SMref_row>1.0) = NaN;

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            Ssp = load(f_sp, 'Ts');
            if isfield(Ssp,'Ts') && ~isempty(Ssp.Ts)
                Ts_row = double(Ssp.Ts(lin_pix));
            end
        else
            [TC, Tsoil1, Tsoil2, okTemp] = read_one_day_gldas_fields( ...
                day_dt, CFG, lat_9km, lon_9km, string(infoY.fy_platform), ...
                GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT);

            if okTemp
                TC_row     = double(TC(lin_pix));
                Tsoil1_row = double(Tsoil1(lin_pix));
                Tsoil2_row = double(Tsoil2(lin_pix));
            end
        end

        TBv_mat(k,:)   = TBv_row;
        TBh_mat(k,:)   = TBh_row;
        IA_mat(k,:)    = IA_row;
        NDVI_mat(k,:)  = NDVI_row;
        SMref_mat(k,:) = SMref_row;
        SF_mat(k,:)    = SF_row;

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            Ts_mat(k,:) = Ts_row;
        else
            TC_mat(k,:)     = TC_row;
            Tsoil1_mat(k,:) = Tsoil1_row;
            Tsoil2_mat(k,:) = Tsoil2_row;
        end
        if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
            fprintf('[D][PRELOAD][PAR] %4d / %4d | %s\n', k, Nt, datestr(day_dt,'yyyy-mm-dd'));
        end
    end
else
    for k = 1:Nt
        day_dt = t_year(k);
        name = datestr(day_dt,'yyyymmdd');

        if mod(k, max(1,CFG.PRINT_EVERY_DAYS))==1 || k==Nt
            fprintf('[D][PRELOAD] %4d / %4d | %s\n', k, Nt, datestr(day_dt,'yyyy-mm-dd'));
        end

        TBv_row    = nan(1, Npix);
        TBh_row    = nan(1, Npix);
        IA_row     = nan(1, Npix);
        NDVI_row   = nan(1, Npix);
        SMref_row  = nan(1, Npix);
        Ts_row     = nan(1, Npix);
        TC_row     = nan(1, Npix);
        Tsoil1_row = nan(1, Npix);
        Tsoil2_row = nan(1, Npix);
        SF_row     = nan(1, Npix);

        if upper(string(CFG.TB_SOURCE))=="FY"
            if upper(string(infoY.fy_platform))=="3B"
                f_tb = fullfile(CFG.fy3b_folder, [name '.mat']);
            else
                f_tb = fullfile(CFG.fy3d_folder, [name '.mat']);
            end
        else
            f_tb = fullfile(CFG.smap_folder, [name '.mat']);
        end

        f_sp   = fullfile(CFG.smap_folder, [name '.mat']);
        f_ndvi = fullfile(CFG.ndvi_folder, [name '.mat']);

        need_ndvi_file = upper(string(CFG.NDVI_MODE))=="DAILY_FILE";

        if exist(f_tb,'file')~=2 || (need_ndvi_file && exist(f_ndvi,'file')~=2)
            fprintf('[MISS][TB/NDVI] %s\n', datestr(day_dt,'yyyy-mm-dd'));

            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;
        end

        need_smap_file = upper(string(CFG.SM_SOURCE))=="SMAP" || ...
                         upper(string(CFG.TEMP_SCHEME))=="ORIG_TS" || ...
                         upper(string(CFG.SF_MODE))=="INVERTED_DAILY";

        if need_smap_file && exist(f_sp,'file')~=2
            fprintf('[MISS][SMAP] %s\n', f_sp);

            TBv_mat(k,:)   = TBv_row;
            TBh_mat(k,:)   = TBh_row;
            IA_mat(k,:)    = IA_row;
            NDVI_mat(k,:)  = NDVI_row;
            SMref_mat(k,:) = SMref_row;
            SF_mat(k,:)    = SF_row;

            if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                Ts_mat(k,:) = Ts_row;
            else
                TC_mat(k,:)     = TC_row;
                Tsoil1_mat(k,:) = Tsoil1_row;
                Tsoil2_mat(k,:) = Tsoil2_row;
            end
            continue;
        end

        if upper(string(CFG.SM_SOURCE))=="DDCA"
            f_ddca = fullfile(CFG.ddca_sm_folder, [name '.mat']);
            if exist(f_ddca,'file')~=2
                fprintf('[MISS][DDCA] %s\n', f_ddca);

                TBv_mat(k,:)   = TBv_row;
                TBh_mat(k,:)   = TBh_row;
                IA_mat(k,:)    = IA_row;
                NDVI_mat(k,:)  = NDVI_row;
                SMref_mat(k,:) = SMref_row;
                SF_mat(k,:)    = SF_row;

                if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
                    Ts_mat(k,:) = Ts_row;
                else
                    TC_mat(k,:)     = TC_row;
                    Tsoil1_mat(k,:) = Tsoil1_row;
                    Tsoil2_mat(k,:) = Tsoil2_row;
                end
                continue;
            end
        else
            f_ddca = '';
        end

        % ===== TB / IA =====
        if upper(string(CFG.TB_SOURCE))=="FY"
            Sfy = load(f_tb, 'TBv','TBh','IA');

            if isfield(Sfy,'TBv')
                TBv_row = double(Sfy.TBv(lin_pix));
            end
            if isfield(Sfy,'TBh')
                TBh_row = double(Sfy.TBh(lin_pix));
            end
            if isfield(Sfy,'IA')
                tmp = double(Sfy.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end

            if upper(string(infoY.fy_platform))=="3B" && ~isempty(MATCH)
                TBv_row = apply_match_row(TBv_row, MATCH.V, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
                TBh_row = apply_match_row(TBh_row, MATCH.H, CFG.MATCH_METHOD, CFG.MATCH_CDF_EXTRAP);
            end

        else
            Ssp_tb = load(f_tb, 'TBv','TBh','IA');

            if isfield(Ssp_tb,'TBv')
                TBv_row = double(Ssp_tb.TBv(lin_pix));
            end
            if isfield(Ssp_tb,'TBh')
                TBh_row = double(Ssp_tb.TBh(lin_pix));
            end
            if isfield(Ssp_tb,'IA')
                tmp = double(Ssp_tb.IA(lin_pix));
                IA_row(isfinite(tmp)) = tmp(isfinite(tmp));
            end
        end

        % ===== NDVI：daily file or DOY climatology =====
        if upper(string(CFG.NDVI_MODE))=="DAILY_FILE"

            Svi = load(f_ndvi, 'NDVI');
            if isfield(Svi,'NDVI')
                NDVI_row = double(Svi.NDVI(lin_pix));
            end

        elseif upper(string(CFG.NDVI_MODE))=="DOY_CLIM"

    doy_k = day(day_dt,'dayofyear');

    if ~isempty(NDVI_DOY_CLIM)
        if size(NDVI_DOY_CLIM,1) ~= 366 || size(NDVI_DOY_CLIM,2) ~= Npix
            error('NDVI_DOY_CLIM 尺寸不匹配：期望 [366 x %d]，实际 [%d x %d]', ...
                Npix, size(NDVI_DOY_CLIM,1), size(NDVI_DOY_CLIM,2));
        end
        NDVI_row = double(NDVI_DOY_CLIM(doy_k,:));
    end

        else
            error('未知 CFG.NDVI_MODE=%s', string(CFG.NDVI_MODE));
        end

        % ===== SF：STATIC or INVERTED_DAILY =====
        if upper(string(CFG.SF_MODE))=="STATIC"

            SSF_local = load(fullfile(CFG.anc_root,'SF.mat'));
            SF_static_local = SSF_local.SF_smap;
            SF_row = double(SF_static_local(lin_pix));

        elseif upper(string(CFG.SF_MODE))=="INVERTED_DAILY"

            doy_k = day(day_dt,'dayofyear');
            f_clim = fullfile(CFG.ndvi_clim_folder, sprintf('%d.mat', doy_k));

            if exist(f_clim,'file')~=2
    error('缺少 NDVI_clim 文件：%s', f_clim);
end

            Sclim = load(f_clim, CFG.ndvi_clim_varname);
            NDVI_clim_grid = Sclim.(CFG.ndvi_clim_varname);
            NDVI_clim_row  = double(NDVI_clim_grid(lin_pix));

            Svwc = load(f_sp, 'vwc');
            if ~isfield(Svwc, 'vwc')
                error('SMAP 日文件缺少变量 vwc：%s', f_sp);
            end

            vwc_row = double(Svwc.vwc(lin_pix));

            SF_row = build_sf_row_daily( ...
                vwc_row, ...
                NDVI_clim_row, ...
                NDVI_clim_max(lin_pix), ...
                NDVI_clim_min(lin_pix), ...
                LC(lin_pix), ...
                CFG.SF_INVERT_MODE);

        else
            error('未知 CFG.SF_MODE=%s', string(CFG.SF_MODE));
        end

        % ===== SMref =====
        if upper(string(CFG.SM_SOURCE))=="SMAP"
            Ssm = load(f_sp, 'sm_dca');
            if isfield(Ssm,'sm_dca')
                SMref_row = double(Ssm.sm_dca(lin_pix));
            end
        else
            Sdd = load(f_ddca, 'SM');
            if isfield(Sdd,'SM')
                SMref_row = double(Sdd.SM(lin_pix));
            end
        end
        SMref_row(SMref_row<-0.01 | SMref_row>1.0) = NaN;

        % ===== 温度 =====
        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

            Ssp = load(f_sp, 'Ts');
            if isfield(Ssp,'Ts') && ~isempty(Ssp.Ts)
                Ts_row = double(Ssp.Ts(lin_pix));
            end

        else
            [TC, Tsoil1, Tsoil2, okTemp] = read_one_day_gldas_fields( ...
                day_dt, CFG, lat_9km, lon_9km, string(infoY.fy_platform), ...
                GLDAS_INDEX, GLDAS_TEMPLATE_ALL, GLDAS_DAY_SLOT);

            if okTemp
                TC_row     = double(TC(lin_pix));
                Tsoil1_row = double(Tsoil1(lin_pix));
                Tsoil2_row = double(Tsoil2(lin_pix));
            end
        end

        TBv_mat(k,:)   = TBv_row;
        TBh_mat(k,:)   = TBh_row;
        IA_mat(k,:)    = IA_row;
        NDVI_mat(k,:)  = NDVI_row;
        SMref_mat(k,:) = SMref_row;
        SF_mat(k,:)    = SF_row;

        if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
            Ts_mat(k,:) = Ts_row;
        else
            TC_mat(k,:)     = TC_row;
            Tsoil1_mat(k,:) = Tsoil1_row;
            Tsoil2_mat(k,:) = Tsoil2_row;
        end
    end
end

YEAR.TBv_mat   = TBv_mat;
YEAR.TBh_mat   = TBh_mat;
YEAR.IA_mat    = IA_mat;
YEAR.NDVI_mat  = NDVI_mat;
YEAR.SMref_mat = SMref_mat;
YEAR.SF_mat    = SF_mat;

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    YEAR.Ts_mat     = Ts_mat;
    YEAR.TC_mat     = [];
    YEAR.Tsoil1_mat = [];
    YEAR.Tsoil2_mat = [];
else
    YEAR.Ts_mat     = [];
    YEAR.TC_mat     = TC_mat;
    YEAR.Tsoil1_mat = Tsoil1_mat;
    YEAR.Tsoil2_mat = Tsoil2_mat;
end
end
function [OK, OUT] = process_one_day_from_preloaded_chunk( ...
    k, t_year, YEAR, CFG, OMEGA_AVG_chunk, ...
    LC, B, BD, CF, NDVI_v_max, NDVI_v_min, ...
    h_map, alpha_map, LAMBDA_TAU, usePar)

OK = false;

% 全部转成列向量
LC         = LC(:);
B          = B(:);
BD         = BD(:);
CF         = CF(:);
NDVI_v_max = NDVI_v_max(:);
NDVI_v_min = NDVI_v_min(:);
h_map      = h_map(:);
alpha_map  = alpha_map(:);

Nc = numel(LC);

OUT = struct();
OUT.SM    = nan(Nc,1,'single');
OUT.VOD   = nan(Nc,1,'single');
OUT.OMEGA = nan(Nc,1,'single');

% ---------- 当前日 avg omega ----------
if isempty(OMEGA_AVG_chunk) || k > size(OMEGA_AVG_chunk,1)
    fprintf('[MISS][AVGOMEGA][CHUNK] 第 %d 天 avg omega 不存在\n', k);
    return;
end

OMEGA_AVG = double(OMEGA_AVG_chunk(k,:)).';

% ---------- 当前日预读输入 ----------
TBv    = double(YEAR.TBv_mat(k,:)).';
TBh    = double(YEAR.TBh_mat(k,:)).';
IA     = double(YEAR.IA_mat(k,:)).';
NDVI   = double(YEAR.NDVI_mat(k,:)).';
SMref  = double(YEAR.SMref_mat(k,:)).';
SF_day = double(YEAR.SF_mat(k,:)).';

Ts     = nan(Nc,1);
TC     = nan(Nc,1);
Tsoil1 = nan(Nc,1);
Tsoil2 = nan(Nc,1);

if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"
    Ts = double(YEAR.Ts_mat(k,:)).';
else
    TC     = double(YEAR.TC_mat(k,:)).';
    Tsoil1 = double(YEAR.Tsoil1_mat(k,:)).';
    Tsoil2 = double(YEAR.Tsoil2_mat(k,:)).';
end

% ---------- Tau ----------
Tau_star = nan(size(TBv));

mask_tau_in = isfinite(NDVI) & isfinite(IA);

Tau_star(mask_tau_in) = Tau( ...
    NDVI(mask_tau_in), ...
    NDVI_v_max(mask_tau_in), ...
    NDVI_v_min(mask_tau_in), ...
    LC(mask_tau_in), ...
    B(mask_tau_in), ...
    SF_day(mask_tau_in), ...
    IA(mask_tau_in), ...
    CFG.TAU_VWC2_MODE);

% ---------- valid_tau ----------
if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

    valid_tau = isfinite(TBv) & isfinite(TBh) & isfinite(Ts) & ...
                isfinite(NDVI) & isfinite(IA) & ...
                isfinite(Tau_star) & isfinite(h_map) & isfinite(alpha_map);

else

    [~, TG] = build_effective_soil_temperature_scheme(SMref, Tsoil1, Tsoil2, CFG);

    valid_tau = isfinite(TBv) & isfinite(TBh) & isfinite(TC) & isfinite(TG) & ...
                isfinite(NDVI) & isfinite(IA) & ...
                isfinite(Tau_star) & isfinite(h_map) & isfinite(alpha_map);
end

% ---------- avg_apply_mode ----------
if upper(string(CFG.avg_apply_mode))=="VALID_ONLY"

    mask_use = valid_tau & isfinite(OMEGA_AVG);

else

    if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

        mask_use = isfinite(TBv) & isfinite(TBh) & isfinite(Ts) & ...
                   isfinite(IA) & isfinite(Tau_star) & ...
                   isfinite(h_map) & isfinite(alpha_map) & ...
                   isfinite(OMEGA_AVG);

    else

        mask_use = isfinite(TBv) & isfinite(TBh) & isfinite(TC) & isfinite(TG) & ...
                   isfinite(IA) & isfinite(Tau_star) & ...
                   isfinite(h_map) & isfinite(alpha_map) & ...
                   isfinite(OMEGA_AVG);
    end
end

% ---------- 若当前 chunk 这一天没有可回代像元 ----------
if ~any(mask_use(:))
    OK = true;
    OUT.OMEGA = single(OMEGA_AVG);
    return;
end

% ---------- 最终使用 omega ----------
OMEGA_USE = nan(size(OMEGA_AVG));
OMEGA_USE(mask_use) = OMEGA_AVG(mask_use);

OUT.OMEGA = single(OMEGA_USE);

porosity = 1 - BD ./ 2.65;
freq_GHz = pick_freq_GHz(CFG);
idx = find(mask_use);

% =========================================================================
% ============================ 单温度回代 =================================
% =========================================================================
if upper(string(CFG.TEMP_SCHEME))=="ORIG_TS"

    if usePar

        SM_tmp  = nan(numel(idx),1,'single');
        VOD_tmp = nan(numel(idx),1,'single');

        parfor ii = 1:numel(idx)

            p = idx(ii);

            [smi, vodi] = DDCA_single_temp( ...
                TBv(p), TBh(p), Ts(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);

            SM_tmp(ii)  = single(smi);
            VOD_tmp(ii) = single(vodi);
        end

        OUT.SM(idx)  = SM_tmp;
        OUT.VOD(idx) = VOD_tmp;

    else

        for ii = 1:numel(idx)

            p = idx(ii);

            [smi, vodi] = DDCA_single_temp( ...
                TBv(p), TBh(p), Ts(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);

            OUT.SM(p)  = single(smi);
            OUT.VOD(p) = single(vodi);
        end
    end

% =========================================================================
% ============================ 双温度回代 =================================
% =========================================================================
else

    [~, TG] = build_effective_soil_temperature_scheme(SMref, Tsoil1, Tsoil2, CFG);

    if usePar

        SM_tmp  = nan(numel(idx),1,'single');
        VOD_tmp = nan(numel(idx),1,'single');

        parfor ii = 1:numel(idx)

            p = idx(ii);

            [smi, vodi] = DDCA_dual_temp( ...
                TBv(p), TBh(p), TC(p), TG(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);

            SM_tmp(ii)  = single(smi);
            VOD_tmp(ii) = single(vodi);
        end

        OUT.SM(idx)  = SM_tmp;
        OUT.VOD(idx) = VOD_tmp;

    else

        for ii = 1:numel(idx)

            p = idx(ii);

            [smi, vodi] = DDCA_dual_temp( ...
                TBv(p), TBh(p), TC(p), TG(p), Tau_star(p), h_map(p), CF(p), OMEGA_USE(p), ...
                porosity(p), freq_GHz, IA(p), alpha_map(p), LAMBDA_TAU);

            OUT.SM(p)  = single(smi);
            OUT.VOD(p) = single(vodi);
        end
    end
end
OK = true;

end
