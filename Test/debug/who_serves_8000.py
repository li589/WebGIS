"""定位监听 :8000/:5175/:6379 的进程命令行与创建时间。

用法: python who_serves_8000.py
"""
import subprocess

PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
SCRIPT = r"""
$c = Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object -First 1
if ($c) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
  "PID: $($p.ProcessId)"
  "Created: $($p.CreationDate)"
  "CmdLine: $($p.CommandLine)"
  "CWD-hint:"
  $env = $p.CommandLine
} else { "no listener on 8000" }
"--- python/celery processes ---"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn|celery|fastapi|start_fastapi' } | ForEach-Object {
  "PID $($_.ProcessId) | $($_.CreationDate) | $($_.CommandLine.Substring(0, [Math]::Min(180, $_.CommandLine.Length)))"
}
"""


def main() -> None:
    r = subprocess.run([PS, "-NoProfile", "-Command", SCRIPT], capture_output=True, text=True, timeout=90)
    print(r.stdout[:4000])
    if r.stderr:
        print("STDERR:", r.stderr[:800])


if __name__ == "__main__":
    main()
