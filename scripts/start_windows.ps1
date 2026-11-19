param([switch]$NoWindow, [switch]$Stop, [string]$DesktopResult, [int]$ExpectedProcessId, [string]$ExpectedStart)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$storage = Join-Path $root 'storage'
$python = Join-Path $root 'runtime\python.exe'
if (!(Test-Path -LiteralPath $python)) { $python = Join-Path $root '.venv\Scripts\python.exe' }
$allowedPaths = @($python)
$venvConfig = Join-Path $root '.venv\pyvenv.cfg'
if (Test-Path -LiteralPath $venvConfig) {
    $pythonHome = Select-String -LiteralPath $venvConfig -Pattern '^home\s*=\s*(.+)$' | Select-Object -First 1
    if ($pythonHome) { $allowedPaths += Join-Path $pythonHome.Matches[0].Groups[1].Value.Trim() 'python.exe' }
}
$statePath = Join-Path $storage 'launcher.json'
$lock = $null

function Get-OwnedProcess($state) {
    if (!$state -or $state.root -ne $root) { return $null }
    $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if (!$process -or $process.Path -notin $allowedPaths) { return $null }
    if ($process.Path -ne $state.executable -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $state.started) { return $null }
    return $process
}
function Test-Ready($url) {
    try { return (Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri "$url/_stcore/health").Content.Trim() -eq 'ok' }
    catch { return $false }
}
function Test-OwnedListener([int]$port, [int]$processId) {
    $pattern = "^\s*TCP\s+127\.0\.0\.1:${port}\s+0\.0\.0\.0:0\s+\S+\s+${processId}\s*$"
    return [bool](netstat.exe -ano -p tcp | Select-String -Pattern $pattern -Quiet)
}
try {
    $null = New-Item -ItemType Directory -Path $storage -Force
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while (!$lock -and [DateTime]::UtcNow -lt $deadline) {
        try { $lock = [IO.File]::Open((Join-Path $storage 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
        catch [IO.IOException] { Start-Sleep -Milliseconds 250 }
    }
    if (!$lock) { throw 'Запуск уже выполняется. Повторите попытку через минуту.' }
    $state = $null
    if (Test-Path -LiteralPath $statePath) {
        try { $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } catch {}
    }
    $owned = Get-OwnedProcess $state
    if ($Stop) {
        if ($ExpectedProcessId -and (!$owned -or $owned.Id -ne $ExpectedProcessId -or $state.started -ne $ExpectedStart)) { exit 0 }
        if ($owned) { $owned.Kill(); $owned.WaitForExit(10000) | Out-Null }
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
        $address = Join-Path $storage 'address.txt'
        if (Test-Path -LiteralPath $address) { Remove-Item -LiteralPath $address }
        Write-Output 'Работа завершена. Сохранённые проверки доступны при следующем запуске.'
        exit 0
    }
    if (!(Test-Path -LiteralPath $python)) { throw 'Запустите install_windows.cmd для установки Python и библиотек.' }
    Write-Output 'Открываем Контур проверки. Пожалуйста, подождите...'
    $startedHere = $false
    if ($owned) {
        $url = "http://127.0.0.1:$($state.port)"
        if (!(Test-Ready $url) -or !(Test-OwnedListener $state.port $owned.Id)) { throw 'Не удалось открыть уже запущенную проверку. Выполните stop_windows.cmd и запустите программу снова.' }
    } else {
        $env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
        $ready = $false
        $startupDeadline = [DateTime]::UtcNow.AddSeconds(52)
        for ($port = 8517; $port -lt 8537; $port++) {
            $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $port)
            try { $listener.Start() } catch { continue } finally { $listener.Stop() }
            $url = "http://127.0.0.1:$port"
            $launchId = [Guid]::NewGuid().ToString('N')
            $pidReport = Join-Path $storage "launcher-$launchId.pid"
            $started = Start-Process -FilePath $python -ArgumentList @('-B','-s','-E','scripts/run_local_server.py',"$port",$launchId) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardError (Join-Path $storage 'server.log') -RedirectStandardOutput (Join-Path $storage 'server-output.log')
            $server = $null
            $portDeadline = [DateTime]::UtcNow.AddSeconds(17)
            try {
                while ([DateTime]::UtcNow -lt $startupDeadline -and [DateTime]::UtcNow -lt $portDeadline -and !$started.HasExited) {
                    Start-Sleep -Milliseconds 350
                    if (!$server -and (Test-Path -LiteralPath $pidReport)) {
                        $processNumber = Get-Content -LiteralPath $pidReport -TotalCount 1
                        if ($processNumber -match '^[1-9][0-9]*$') {
                            $candidate = Get-Process -Id ([int]$processNumber) -ErrorAction SilentlyContinue
                            if ($candidate -and $candidate.Path -in $allowedPaths -and $candidate.StartTime -ge $started.StartTime) { $server = $candidate }
                        }
                    }
                    if ($server -and (Test-Ready $url) -and (Test-OwnedListener $port $server.Id)) {
                        $ready = $true
                        break
                    }
                }
            } finally {
                if (Test-Path -LiteralPath $pidReport) { Remove-Item -LiteralPath $pidReport }
                if (!$ready) {
                    if ($server -and !$server.HasExited) { $server.Kill(); $server.WaitForExit(10000) | Out-Null }
                    if (!$started.HasExited) { $started.Kill(); $started.WaitForExit(10000) | Out-Null }
                }
            }
            if ($ready) { break }
            if ([DateTime]::UtcNow -ge $startupDeadline) { break }
        }
        if (!$ready) { throw 'Не удалось запустить приложение. Подробности находятся в storage\server.log.' }
        $state = @{root=$root; pid=$server.Id; executable=$server.Path; started=$server.StartTime.ToUniversalTime().Ticks.ToString(); port=$port}
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        $startedHere = $true
    }
    $url | Set-Content -LiteralPath (Join-Path $storage 'address.txt') -Encoding UTF8
    if (!$NoWindow) {
        $edge = @(
            (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
            (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        $opened = $false
        if ($edge) {
            try {
                $profile = Join-Path $storage 'browser-profile'
                $window = Start-Process -FilePath $edge -ArgumentList @("--app=$url", "--user-data-dir=`"$profile`"", '--no-first-run','--no-default-browser-check') -PassThru
                Start-Sleep -Milliseconds 800
                $opened = !$window.HasExited -or $window.ExitCode -eq 0
            } catch {}
        }
        if (!$opened) { Start-Process $url }
    }
    Write-Output $url
    if ($DesktopResult) {
        $protocol = @($url)
        if ($startedHere) { $protocol += "KONTUR_OWNER=$($state.pid),$($state.started)" }
        Set-Content -LiteralPath $DesktopResult -Value $protocol -Encoding UTF8
    }
    Write-Output 'Для полного завершения работы используйте stop_windows.cmd.'
} catch {
    if (!$NoWindow) {
        Add-Type -AssemblyName System.Windows.Forms
        $null = [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Контур проверки')
    }
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($lock) { $lock.Dispose() }
}
