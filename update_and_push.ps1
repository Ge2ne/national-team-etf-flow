$ErrorActionPreference = "Continue"
# 按需修改这三处: 仓库所在目录 / PAT 文件位置 / 推送地址里的用户名
$base   = Split-Path -Parent $PSScriptRoot
$repo   = Join-Path $base "national-team-etf-flow"
$secret = Join-Path $env:USERPROFILE ".gh_pat.txt"
$lock   = Join-Path $base ".update.lock"
$log    = Join-Path $base "auto_update.log"

if (Test-Path $lock) { Write-Output "previous run still active, skip"; exit 0 }
Set-Content -Path $lock -Value "1" -Encoding utf8
function Log($m){ $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "  " + $m; Add-Content -Path $log -Value $line -Encoding utf8; Write-Output $m }
try {
  Set-Location $base
  python refresh_national_team_etf.py
  if ($LASTEXITCODE -ne 0) { Log "refresh failed, exit=$LASTEXITCODE"; exit 0 }

  Copy-Item (Join-Path $base "report_latest.html") (Join-Path $repo "index.html") -Force
  Copy-Item (Join-Path $base "refresh_national_team_etf.py")  (Join-Path $repo "refresh.py") -Force

  Set-Location $repo
  git add index.html refresh.py
  git diff --cached --quiet
  if ($LASTEXITCODE -eq 0) {
    Log "no change, skip push"
  } else {
    if (-not (Test-Path $secret)) { Log "secret missing, skip push"; exit 0 }
    $tok = (Get-Content $secret -Raw).Trim()
    git -c user.name="wj624" -c user.email="wj624@users.noreply.github.com" commit -m ("chore: auto refresh national team ETF report " + (Get-Date -Format "yyyyMMdd HH:mm")) | Out-Null
    if ($LASTEXITCODE -ne 0) { Log "commit failed"; exit 0 }
    $env:GIT_TERMINAL_PROMPT = "0"
    $url = "https://x-access-token:$tok@github.com/wj624/national-team-etf-flow.git"
    git -c credential.helper= push $url main 2>$null
    if ($LASTEXITCODE -eq 0) { Log "pushed to GitHub" } else { Log "push failed (network?)" }
  }
} finally {
  Remove-Item $lock -Force -ErrorAction SilentlyContinue
}