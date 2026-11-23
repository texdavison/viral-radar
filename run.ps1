# Viral Idea Radar - collect signals and push them to GitHub.
# Windows Task Scheduler runs this every 3 hours (see CLAUDE.md).
$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot
$log = Join-Path $PSScriptRoot "last-run.log"
"=== $(Get-Date -Format o) ===" | Out-File $log -Encoding utf8

# Use the Python launcher if present, otherwise python on PATH.
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }

git pull --rebase --quiet 2>&1 | Out-File $log -Append -Encoding utf8
& $py collect.py 2>&1 | Out-File $log -Append -Encoding utf8

git add signals 2>&1 | Out-File $log -Append -Encoding utf8
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit --quiet -m "signals $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-File $log -Append -Encoding utf8
    git push --quiet 2>&1 | Out-File $log -Append -Encoding utf8
    "pushed" | Out-File $log -Append -Encoding utf8
} else {
    "no changes" | Out-File $log -Append -Encoding utf8
}
