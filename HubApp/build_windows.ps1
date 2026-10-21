# Build de l app Hub (coquille) pour Windows -> %LOCALAPPDATA%\Programs\Hub
# + raccourcis menu Demarrer et Bureau. Prerequis : Python 3.14 (py), Build
# Tools avec "Developpement Desktop en C++" (MSVC, CMake, SDK Windows).
$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"; $env:PYTHONUTF8 = "1"; $env:TERM = "dumb"
$repo = Split-Path -Parent $PSScriptRoot
git -C $repo pull -q
git -C $repo log -1 --oneline
$V = "$env:USERPROFILE\.hub_build_venv"
if (-not (Test-Path "$V\Scripts\flet.exe")) {
  py -3.14 -m venv $V
  & "$V\Scripts\pip" -q install "flet[all]==1.0.4"
}
Set-Location "$repo\HubApp"
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
& "$V\Scripts\flet" build windows --no-compile-packages --yes -v 2>&1 | Select-Object -Last 60
$src = "$repo\HubApp\build\windows"
$dst = "$env:LOCALAPPDATA\Programs\Hub"
Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue
robocopy $src $dst /E /NFL /NDL /NJH /NJS /NP | Out-Null  # Copy-Item imbriquait
$ws = New-Object -ComObject WScript.Shell
foreach ($d in @([Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop"))) {
  $s = $ws.CreateShortcut("$d\Hub.lnk"); $s.TargetPath = "$dst\hub.exe"; $s.WorkingDirectory = $dst; $s.Save()
}
"{0:N0} Mo" -f ((Get-ChildItem -Recurse $dst | Measure-Object Length -Sum).Sum / 1MB)
