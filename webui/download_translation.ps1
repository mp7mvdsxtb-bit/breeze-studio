$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$target = Join-Path (Split-Path $PSScriptRoot -Parent) 'translation-model'
New-Item -ItemType Directory -Path $target -Force | Out-Null
$model = Invoke-RestMethod 'https://huggingface.co/api/models/Helsinki-NLP/opus-mt-zh-en?blobs=true' -TimeoutSec 40
$model | ConvertTo-Json -Depth 10 | Set-Content (Join-Path $target 'download-manifest.json') -Encoding utf8
$wanted = @('README.md','config.json','generation_config.json','source.spm','target.spm','tokenizer_config.json','vocab.json','pytorch_model.bin')
foreach ($file in $model.siblings | Where-Object rfilename -In $wanted) {
    $destination = Join-Path $target $file.rfilename
    $url = 'https://huggingface.co/Helsinki-NLP/opus-mt-zh-en/resolve/' + $model.sha + '/' + $file.rfilename
    if (!(Test-Path -LiteralPath $destination) -or (Get-Item -LiteralPath $destination).Length -ne $file.size) {
        if ($file.size -lt 10000000) {
            Invoke-WebRequest -Uri ($url + '?fresh=' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -OutFile $destination -TimeoutSec 60
        } else {
            $chunks = @()
            for ($start=0L; $start -lt $file.size; $start+=67108864) {
                $chunks += [pscustomobject]@{Start=$start;End=[Math]::Min($start+67108863,$file.size-1);Path=($destination+'.'+$start);Url=$url}
            }
            $chunks | ForEach-Object -Parallel {
                $ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';$chunk=$_
                Invoke-WebRequest -Uri ($chunk.Url+'?chunk='+$chunk.Start+'&fresh='+[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) -Headers @{Range=('bytes='+$chunk.Start+'-'+$chunk.End)} -OutFile $chunk.Path -TimeoutSec 180 -MaximumRetryCount 3
                if ((Get-Item -LiteralPath $chunk.Path).Length -ne $chunk.End-$chunk.Start+1) {throw 'Chunk size mismatch'}
                Write-Output ('Downloaded translation chunk '+$chunk.Start)
            } -ThrottleLimit 4
            $outputFile=[IO.File]::Create($destination)
            try {foreach ($chunk in $chunks) {$inputFile=[IO.File]::OpenRead($chunk.Path);try {$inputFile.CopyTo($outputFile)} finally {$inputFile.Dispose()}}} finally {$outputFile.Dispose()}
            foreach ($chunk in $chunks) {Remove-Item -LiteralPath $chunk.Path}
        }
    }
    if ((Get-Item -LiteralPath $destination).Length -ne $file.size) {throw 'File size mismatch'}
    if ($file.lfs -and (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLower() -ne $file.lfs.sha256) {throw 'Weight hash mismatch'}
}
Write-Output 'TRANSLATION_MODEL_VERIFIED'
