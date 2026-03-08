param(
    [string]$Destination = "release\github"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root $Destination

if (Test-Path $target) {
    Remove-Item -Path $target -Recurse -Force
}

New-Item -ItemType Directory -Path $target | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "src") | Out-Null

$fileItems = @(
    "pyproject.toml",
    "README.md",
    ".gitignore",
    ".dockerignore",
    ".env.example",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Dockerfile",
    "docker-compose.yml"
)

foreach ($item in $fileItems) {
    $sourcePath = Join-Path $root $item
    if (Test-Path $sourcePath) {
        Copy-Item -Path $sourcePath -Destination (Join-Path $target $item) -Force
    }
}

Copy-Item -Path (Join-Path $root "src\douyin_pipeline") -Destination (Join-Path $target "src") -Recurse -Force

if (Test-Path (Join-Path $root "docs")) {
    Copy-Item -Path (Join-Path $root "docs") -Destination $target -Recurse -Force
}

if (Test-Path (Join-Path $root "scripts")) {
    Copy-Item -Path (Join-Path $root "scripts") -Destination $target -Recurse -Force
}

if (Test-Path (Join-Path $root "tests")) {
    Copy-Item -Path (Join-Path $root "tests") -Destination $target -Recurse -Force
}

if (Test-Path (Join-Path $root ".github")) {
    Copy-Item -Path (Join-Path $root ".github") -Destination $target -Recurse -Force
}

Get-ChildItem -Path $target -Recurse -Directory -Filter "*.egg-info" | Remove-Item -Recurse -Force
Get-ChildItem -Path $target -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $target -Recurse -File -Include "*.pyc" | Remove-Item -Force

Write-Host "Sanitized GitHub export created at $target"
