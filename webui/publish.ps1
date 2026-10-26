$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$gh = Join-Path $root 'tools\github-cli\bin\gh.exe'
if (!(Test-Path -LiteralPath $gh)) { $gh = (Get-Command gh -ErrorAction Stop).Source }
& $gh auth status
if ($LASTEXITCODE) { throw 'Run gh auth login first.' }
$owner = & $gh api user --jq .login
if ($LASTEXITCODE -or $owner -notmatch '^[A-Za-z0-9-]+$') { throw 'Cannot determine authenticated account.' }
$repo = "$owner/breeze-studio"
$version = (Get-Content (Join-Path $root 'version.json') -Raw | ConvertFrom-Json).version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid version' }
@{version=$version;repository=$repo} | ConvertTo-Json | Set-Content (Join-Path $root 'version.json') -Encoding utf8
$source = Join-Path (Split-Path $root -Parent) 'breeze-studio-source'
& (Join-Path $root 'venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'prepare_source.py')
if ($LASTEXITCODE) { throw 'Source preparation failed.' }
Push-Location $source
try {
    if (!(Test-Path -LiteralPath '.git')) { git init -b main }
    if ($LASTEXITCODE) { throw 'git init failed' }
    git add --all
    if ($LASTEXITCODE) { throw 'git add failed' }
    git diff --cached --quiet
    if ($LASTEXITCODE -eq 1) { git commit -m 'Build Breeze Studio with English production tools and startup updates' }
    $ErrorActionPreference = 'Continue'
    & $gh repo view $repo --json isPrivate 2>$null | Out-Null
    $missingRepository = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($missingRepository) {
        & $gh repo create $repo --private --source . --remote origin --push
        if ($LASTEXITCODE) { throw 'Private repository creation failed.' }
    } else {
        $privacy = & $gh repo view $repo --json isPrivate --jq .isPrivate
        if ($privacy -ne 'true') { throw 'Repository exists but is not private; stopped.' }
        $remote = git remote get-url origin 2>$null
        if (!$remote) { git remote add origin "https://github.com/$repo.git" }
        elseif ($remote -ne "https://github.com/$repo.git") { throw 'Unexpected git remote; stopped.' }
        git push -u origin main
        if ($LASTEXITCODE) { throw 'Push failed.' }
    }
    & (Join-Path $root 'venv\Scripts\python.exe') webui\release.py dist
    $ErrorActionPreference = 'Continue'
    & $gh release view "v$version" --repo $repo 2>$null | Out-Null
    $missingRelease = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($missingRelease) {
        & $gh release create "v$version" dist\breeze-studio-update.zip dist\breeze-studio-update.sha256 --repo $repo --target main --title "Breeze Studio $version" --notes 'Private source release. Models and local audio are excluded.'
        if ($LASTEXITCODE) { throw 'Release creation failed.' }
    }
    Write-Host "Published: https://github.com/$repo"
} finally { Pop-Location }
