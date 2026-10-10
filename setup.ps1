# Installation complete en une commande (Windows, PowerShell) :
#   irm https://raw.githubusercontent.com/PictorSomni/Image_manipulations/main/setup.ps1 | iex
# Installe Python, Git et ImageMagick (winget), telecharge Hub dans
# %USERPROFILE%\Image_manipulations, installe les dependances, cree un
# raccourci sur le Bureau et lance Hub.
$ErrorActionPreference = "Stop"
$Repo = "https://github.com/PictorSomni/Image_manipulations.git"
$Dir = Join-Path $env:USERPROFILE "Image_manipulations"

foreach ($id in "Python.Python.3.12", "Git.Git",
                "ImageMagick.ImageMagick") {
    winget install --id $id -e --silent --accept-package-agreements `
        --accept-source-agreements | Out-Null
}
# PATH mis a jour par les installations ci-dessus
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [Environment]::GetEnvironmentVariable("Path", "User")

if (Test-Path (Join-Path $Dir ".git")) {
    git -C $Dir pull --ff-only
} else {
    git clone --depth 1 $Repo $Dir
}
& cmd /c "`"$Dir\install.bat`""

# Raccourci Bureau (pythonw : pas de console)
$pyw = (Get-Command pythonw).Source
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Hub.lnk"))
$lnk.TargetPath = $pyw
$lnk.Arguments = "`"$Dir\Hub.pyw`""
$lnk.WorkingDirectory = $Dir
$lnk.IconLocation = "$Dir\assets\icon.ico"
$lnk.Save()

Write-Host "[OK] Hub est installe. Au premier lancement, renseignez vos identifiants."
Start-Process $pyw -ArgumentList "`"$Dir\Hub.pyw`"" -WorkingDirectory $Dir
