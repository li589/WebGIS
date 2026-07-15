@echo off
cd /d "d:\temp_desktop\Proj\Comprehensive Geographic Data Analysis system\Tools"
python -u download_curated.py > reports\download_log2.txt 2>&1
echo EXIT_CODE=%ERRORLEVEL% >> reports\download_log2.txt
