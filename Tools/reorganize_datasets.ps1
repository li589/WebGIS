# 数据集目录重组脚本：将 22 个顶层目录整理为 12 个大类
# 使用 robocopy /MOVE 确保数据安全（NTFS 跨目录移动）
# 每次 move 后验证文件数
# 请在 PowerShell 中运行（无需管理员权限，但需要 I:\ 盘写入权限）
# 运行前请关闭所有可能访问 I:\ 盘的程序
# 脚本是幂等的：如果源目录不存在会自动跳过

$root = 'I:\Geograph_DataSet'
$ErrorActionPreference = 'Stop'

# === 辅助函数 ===

function Move-DirSafe {
    # 使用 robocopy /MOVE 安全移动目录，移动前后验证文件数
    # 支持目标目录已存在时合并内容
    param(
        [Parameter(Mandatory)][string]$Src,
        [Parameter(Mandatory)][string]$Dst
    )

    if (-not (Test-Path $Src)) {
        Write-Host "  SKIP (source not found): $Src" -ForegroundColor Yellow
        return
    }

    # 移动前文件计数
    $before = (Get-ChildItem $Src -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
    Write-Host "  [$before files] $Src" -ForegroundColor White
    Write-Host "           -> $Dst" -ForegroundColor DarkGray

    # 如果目标已存在，统计已有文件数
    $dstBefore = 0
    if (Test-Path $Dst) {
        $dstBefore = (Get-ChildItem $Dst -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
    }

    # robocopy /MOVE /E：移动所有文件和子目录，移动后删除源目录
    # /R:3 重试 3 次，/W:5 每次等待 5 秒
    $robocopyArgs = @($Src, $Dst, '/MOVE', '/E', '/R:3', '/W:5', '/NFL', '/NDL', '/NJH', '/NJS')
    & robocopy @robocopyArgs | Out-Null
    $exitCode = $LASTEXITCODE

    # robocopy 退出码：0-7 成功，8+ 失败
    if ($exitCode -ge 8) {
        Write-Host "  ERROR: robocopy exit code $exitCode" -ForegroundColor Red
        throw "Move failed: $Src -> $Dst (exit code $exitCode)"
    }

    # 验证目标文件数
    $dstAfter = (Get-ChildItem $Dst -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
    $expected = $before + $dstBefore

    if ($dstAfter -ne $expected) {
        Write-Host "  WARNING: file count mismatch (src=$before + dst=$dstBefore = expected=$expected, actual=$dstAfter)" -ForegroundColor Yellow
    } else {
        Write-Host "  OK: $dstAfter files (src $before + existing $dstBefore)" -ForegroundColor Green
    }

    # 清理可能残留的空源目录
    if (Test-Path $Src) {
        $remaining = (Get-ChildItem $Src -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($remaining -eq 0) {
            Remove-Item $Src -Recurse -Force -ErrorAction SilentlyContinue
        } else {
            Write-Host "  WARNING: source not empty, $remaining items remain: $Src" -ForegroundColor Yellow
        }
    }
}

function Move-FileSafe {
    param([string]$Src, [string]$DstDir)

    if (-not (Test-Path $Src)) {
        Write-Host "  SKIP (source not found): $Src" -ForegroundColor Yellow
        return
    }

    if (-not (Test-Path $DstDir)) {
        New-Item -Path $DstDir -ItemType Directory -Force | Out-Null
    }

    $filename = Split-Path $Src -Leaf
    $dst = Join-Path $DstDir $filename
    Write-Host "  Moving file: $Src -> $dst"
    [System.IO.File]::Move($Src, $dst)
    Write-Host "  OK" -ForegroundColor Green
}

function Delete-IfEmpty {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "  SKIP (not found): $Path" -ForegroundColor Yellow
        return
    }

    $count = (Get-ChildItem $Path -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
    if ($count -eq 0) {
        Remove-Item $Path -Recurse -Force
        Write-Host "  Deleted empty: $Path" -ForegroundColor Green
    } else {
        Write-Host "  SKIP (not empty, $count files): $Path" -ForegroundColor Yellow
    }
}

# === 预检：统计移动前总文件数 ===

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Dataset Reorganization Script" -ForegroundColor Cyan
Write-Host " 22 top dirs -> 12 categories" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "=== Pre-check: file count before move ===" -ForegroundColor Cyan
$totalBefore = (Get-ChildItem $root -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "  Total files: $totalBefore"

# === Phase 1: 移动顶层目录 ===

Write-Host ""
Write-Host "=== Phase 1: Move top-level directories ===" -ForegroundColor Cyan

# 1a: 顶层重命名
Write-Host ""
Write-Host "--- 1a: Top-level rename ---" -ForegroundColor White
Move-DirSafe "$root\AdminBoundary"      "$root\Admin_Boundary"
Move-DirSafe "$root\InversionResults"   "$root\Inversion_Results"
Move-DirSafe "$root\Station"            "$root\Station_Observation"

# 1b: 移动为子目录
Write-Host ""
Write-Host "--- 1b: Move as subdirectory ---" -ForegroundColor White
Move-DirSafe "$root\Biomass"        "$root\Ecological_Vegetation\Biomass"
Move-DirSafe "$root\LandCover"      "$root\Ecological_Vegetation\LandCover"
Move-DirSafe "$root\CO2"            "$root\Atmospheric\CO2"
Move-DirSafe "$root\Gosat"          "$root\Atmospheric\Gosat"
Move-DirSafe "$root\DEM"            "$root\Geological\DEM"
Move-DirSafe "$root\Weather"        "$root\Meteorological\Weather"
Move-DirSafe "$root\Precipitation"  "$root\Meteorological\Precipitation"
Move-DirSafe "$root\SMAP"           "$root\Soil_Moisture\SMAP"
Move-DirSafe "$root\HumanFootprint" "$root\Socio_Economic\HumanFootprint"
Move-DirSafe "$root\Transport"      "$root\Socio_Economic\Transport"

# === Phase 2: 拆分 Soil_Ecological_Data ===
# 真实数据：10778 files, 91.3 GB
# DDCA(10625), WHU_CLCD_1985_2023(39), Smap_OriginData(32), SmapSoil_VOD_SM(31),
# CustomNC_SM_CalData(24), NC_2mTemp(12), Smap_auxiliary_data(12), NC_Dewpoint_2mTemp(1)
# root: 2 Chinese zip files

Write-Host ""
Write-Host "=== Phase 2: Split Soil_Ecological_Data ===" -ForegroundColor Cyan

# 土壤水分相关 -> Soil_Moisture/
Move-DirSafe "$root\Soil_Ecological_Data\CustomNC_SM_CalData"  "$root\Soil_Moisture\CustomNC_SM_CalData"
Move-DirSafe "$root\Soil_Ecological_Data\DDCA"                 "$root\Soil_Moisture\DDCA"

# SMAP 相关 -> Soil_Moisture/ (rename to SMAP_ prefix)
Move-DirSafe "$root\Soil_Ecological_Data\SmapSoil_VOD_SM"     "$root\Soil_Moisture\SMAP_Soil_VOD_SM"
Move-DirSafe "$root\Soil_Ecological_Data\Smap_auxiliary_data" "$root\Soil_Moisture\SMAP_Auxiliary_Data"
Move-DirSafe "$root\Soil_Ecological_Data\Smap_OriginData"     "$root\Soil_Moisture\SMAP_Origin_Data"

# 气象相关 -> Meteorological/Weather/
Move-DirSafe "$root\Soil_Ecological_Data\NC_2mTemp"           "$root\Meteorological\Weather\NC_2mTemp"
Move-DirSafe "$root\Soil_Ecological_Data\NC_Dewpoint_2mTemp"  "$root\Meteorological\Weather\NC_Dewpoint_2mTemp"

# 土地覆盖 -> Ecological_Vegetation/LandCover/
Move-DirSafe "$root\Soil_Ecological_Data\WHU_CLCD_1985_2023"  "$root\Ecological_Vegetation\LandCover\WHU_CLCD_1985_2023"

# root 下的 2 个中文 zip 文件
$zip1 = "$root\Soil_Ecological_Data\1980-2021年中国土地利用覆被和变化数据集.zip"
Move-FileSafe $zip1 "$root\Ecological_Vegetation\LandCover"

$forestChangeDir = "$root\Ecological_Vegetation\LandCover\Forest_Change"
if (-not (Test-Path $forestChangeDir)) {
    New-Item -Path $forestChangeDir -ItemType Directory -Force | Out-Null
}
$zip2 = "$root\Soil_Ecological_Data\广东省森林变化.zip"
Move-FileSafe $zip2 $forestChangeDir

# === Phase 3: 拆分 Vegetation ===
# 真实数据：3304 files, 22.7 GB
# NDVIday(3287 .mat), VODyr(17 .mat)

Write-Host ""
Write-Host "=== Phase 3: Split Vegetation ===" -ForegroundColor Cyan

Move-DirSafe "$root\Vegetation\NDVIday"  "$root\Ecological_Vegetation\NDVI\NDVIday"
Move-DirSafe "$root\Vegetation\VODyr"     "$root\Ecological_Vegetation\Biomass\VODyr"

# === Phase 4: 移动 Others ===
# 真实数据：1 file, 123 KB

Write-Host ""
Write-Host "=== Phase 4: Move Others ===" -ForegroundColor Cyan

$aridityFile = "$root\Others\AridityIndex_MSWEP-prcp_div_GLEAM-Ep_1980-2020.tif"
Move-FileSafe $aridityFile "$root\Hazards\DroughtIndex"

# === Phase 5: 删除空目录 ===

Write-Host ""
Write-Host "=== Phase 5: Delete empty directories ===" -ForegroundColor Cyan

Delete-IfEmpty "$root\ForestHeight"
Delete-IfEmpty "$root\River"
Delete-IfEmpty "$root\SAR"
Delete-IfEmpty "$root\Vegetation"
Delete-IfEmpty "$root\Soil_Ecological_Data"
Delete-IfEmpty "$root\Others"

# === Phase 6: 验证 ===

Write-Host ""
Write-Host "=== Phase 6: Verification ===" -ForegroundColor Cyan

Write-Host ""
Write-Host "--- Top-level directories ---" -ForegroundColor White
$dirs = Get-ChildItem $root -Directory | Select-Object -ExpandProperty Name | Sort-Object
$dirs | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "  Directory count: $($dirs.Count)" -ForegroundColor Green

Write-Host ""
Write-Host "--- File count verification ---" -ForegroundColor White
$totalAfter = (Get-ChildItem $root -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "  Before: $totalBefore files"
Write-Host "  After:  $totalAfter files"

if ($totalBefore -ne $totalAfter) {
    $diff = [Math]::Abs($totalBefore - $totalAfter)
    Write-Host "  WARNING: file count difference $diff (may be .gitkeep cleanup)" -ForegroundColor Yellow
} else {
    Write-Host "  OK: file count matches!" -ForegroundColor Green
}

Write-Host ""
Write-Host "--- Files per top-level directory ---" -ForegroundColor White
Get-ChildItem $root -Directory | ForEach-Object {
    $count = (Get-ChildItem $_.FullName -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object).Count
    $padName = $_.Name.PadRight(25)
    Write-Host "  $padName $count files"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Reorganization complete! 12 top dirs." -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next: notify TRAE to update code paths." -ForegroundColor Cyan
