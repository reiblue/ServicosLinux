# NOME DO SERVIÇO (como está registrado no Windows)
$serviceName   = "SmartClassroom"

# Caminho do deploy central (servidor)
$sharePath     = "\\10.11.102.130\deploy\UpdatePrograms\SmartClassroom"

# Pasta onde o serviço está instalado localmente
$localPath     = "C:\Program Files\SmartClassroom"

# Arquivos de versão
$remoteVersionFile = Join-Path $sharePath "Version.txt"
$localVersionFile  = Join-Path $localPath "Version.txt"

# Lê versão remota
if (-not (Test-Path $remoteVersionFile)) {
    Write-Host "Arquivo de versão remoto não encontrado. Saindo."
    exit 1
}
$remoteVersion = Get-Content $remoteVersionFile | Select-Object -First 1

# Lê versão local (ou assume 0.0.0 se não existir)
if (Test-Path $localVersionFile) {
    $localVersion = Get-Content $localVersionFile | Select-Object -First 1
} else {
    $localVersion = "0.0.0"
}

Write-Host "Versão remota: $remoteVersion"
Write-Host "Versão local : $localVersion"

# Converte pra [version] pra comparar corretamente (1.0.10 > 1.0.2)
try {
    $remoteV = [version]$remoteVersion
    $localV  = [version]$localVersion
} catch {
    Write-Host "Erro ao interpretar versões. Saindo."
    exit 1
}

if ($remoteV -le $localV) {
    Write-Host "Nenhuma atualização necessária."
    exit 0
}

Write-Host "Atualização encontrada! Parando serviço..."

# Para o serviço
try {
    if ((Get-Service -Name $serviceName -ErrorAction SilentlyContinue)) {
        Stop-Service -Name $serviceName -Force -ErrorAction Stop
        Start-Sleep -Seconds 5
    }
} catch {
    Write-Host "Não foi possível parar o serviço: $_"
}

Write-Host "Finalizando programas..."

Get-Process -Name "SmartLabKeepToAwake" -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "Copiando arquivos do servidor..."

# Garante que a pasta local existe
if (-not (Test-Path $localPath)) {
    New-Item -ItemType Directory -Path $localPath | Out-Null
}

# Copia tudo do servidor para local
Copy-Item -Path "$sharePath\*" -Destination $localPath -Recurse -Force

# Atualiza o version.txt local
Set-Content -Path $localVersionFile -Value $remoteVersion

Write-Host "Arquivos atualizados. Iniciando serviço..."

try {
    Start-Service -Name $serviceName
    Write-Host "Serviço iniciado com sucesso."
} catch {
    Write-Host "Erro ao iniciar o serviço: $_"
    exit 1
}
