# Один этап в отдельном окне PowerShell (для скриншотов терминала). По окончании создается screenshots\_done_<этап>.
param([string]$Stage)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$Host.UI.RawUI.WindowTitle = "hw3-$Stage"
Set-Location "$PSScriptRoot\.."
$py = ".\.venv\Scripts\python.exe"
function Cmd($t) { Write-Host "PS> $t" -ForegroundColor Yellow }

switch ($Stage) {
    "mr" {
        Cmd "python src/mapreduce.py --mode stream --workers 4"
        & $py src\mapreduce.py --mode stream --workers 4
    }
    "duckdb" {
        Cmd "python src/duckdb_skills.py"
        & $py src\duckdb_skills.py
    }
    "verify" {
        Cmd "python src/verify.py"
        & $py src\verify.py
    }
    "fail" {
        Cmd "python src/mapreduce.py --mode stream --workers 4 --fail-task 3 --out-prefix mapreduce_failtest"
        & $py src\mapreduce.py --mode stream --workers 4 --fail-task 3 --out-prefix mapreduce_failtest
        Write-Host ""
        Cmd "Get-FileHash results\mapreduce\*.csv vs results\mapreduce_failtest\*.csv"
        foreach ($f in "skills_k1.csv", "pairs_k2.csv", "triples_k3.csv") {
            $a = (Get-FileHash "results\mapreduce\$f").Hash; $b = (Get-FileHash "results\mapreduce_failtest\$f").Hash
            Write-Host ("{0,-16} обычный {1}  с отказом {2}  совпадает: {3}" -f $f, $a.Substring(0, 16), $b.Substring(0, 16), ($a -eq $b))
        }
    }
    "profile" {
        Cmd "python src/profile_runs.py --runs 3 mr_naive_w1 mr_stream_w4 duckdb"
        & $py src\profile_runs.py --runs 3 mr_naive_w1 mr_stream_w4 duckdb
    }
}
New-Item -ItemType File -Force "screenshots\_done_$Stage" | Out-Null
# окно остается открытым без приглашения ввода (случайные нажатия клавиш не попадут на скриншот)
Start-Sleep -Seconds 600
