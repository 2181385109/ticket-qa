# 混合回放(v2 评估,作者 2026-09-27 决定):请求与源运行逐字节一致的任务回放源运行的模型输出,不一致的(预期集合 = 纯回放运行里请求不一致的任务)
# 在当前工作区的服务上用真实模型重新采样,每个一次调用。代码与验证见 tests/llm_security/llmsec/hybrid.py。
#
# 本脚本一条命令做完:
#   1. 打包当前工作区的服务(可 -SkipBuild);
#   2. 停掉当前服务(logs/app.pid),以真实模式启动——LLM_BASE_URL 指向 run_eval 起的混合代理;
#   3. run_eval.py hybrid <Source> <Replay>:跑与源运行相同的任务 → hybrid_check.md 验证 → 通过才生成 report.md、compare.md、resample_compare.md;
#   4. 无论成败,以挡板模式重启服务(接口自动化默认走挡板)。
#
# API key(计划 §2-7):只在本脚本这一个进程里把 -KeyFile 的内容读进环境变量 LLM_API_KEY(服务子进程继承,重新采样时由服务带到代理、代理转发给上游),
# 不显示、不写文件、不 setx;自检只输出"前缀是否为 sk-"和长度。挡板模式重启前清掉。
#
# 用法(仓库根目录,PowerShell):
#   powershell -ExecutionPolicy Bypass -File tests\llm_security\tools\hybrid.ps1 -KeyFile '<key 文件路径>' `
#       -Source tests\llm_security\reports\phase2-v1-20260926T040541Z -Replay tests\llm_security\reports\phase2-v2-replay-20260926T082544Z `
#       -JavaHome D:\tools\jdk-17 -Maven D:\tools\maven\bin\mvn.cmd -Python E:\python\python.exe
# 不要把输出接管道:最后重启的服务进程会继承管道句柄,调用方会一直等。要留日志就重定向到文件。
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Replay,
    [string]$KeyFile,
    [string]$RunLabel = "v2-hybrid",
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$Maven = "mvn",
    [string]$Python = "python",
    [int]$HealthTimeoutSeconds = 180,
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$RunEval = Join-Path $Repo "tests\llm_security\run_eval.py"
$PidFile = Join-Path $Repo "logs\app.pid"
$ServiceDir = Join-Path $Repo "service"
$Java = if ($JavaHome) { Join-Path $JavaHome "bin\java.exe" } else { "java.exe" }
if ($JavaHome) { $env:JAVA_HOME = $JavaHome }

function Say($msg) { Write-Host "[hybrid] $msg" }

function Stop-TicketService {
    if (Test-Path $PidFile) {
        $old = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($old) {
            try { Stop-Process -Id ([int]$old) -Force -ErrorAction Stop; Say "已停止服务 pid=$old" } catch { }
        }
    }
    for ($i = 0; $i -lt 30; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8080/actuator/health | Out-Null; Start-Sleep 1 }
        catch { return }
    }
    throw "8080 端口上仍有服务在响应,先手动停掉它"
}

function Start-TicketService([string]$Mode) {
    $env:LLM_MODE = $Mode
    $jarArgs = @('-Dfile.encoding=UTF-8', '-Xms1g', '-Xmx1g', '-XX:+UseG1GC', '-jar', 'target\ticket-qa-service-0.1.0.jar')
    if ($Mode -eq "real") {
        $env:LLM_BASE_URL = "http://127.0.0.1:18090"
        # 与源运行相同的评测配置(计划 §4):放宽超时、熔断阈值
        $jarArgs += @('--llm.timeout-ms=30000', '--llm.circuit.failure-threshold=100000')
    } else {
        Remove-Item Env:LLM_BASE_URL -ErrorAction SilentlyContinue
        Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force (Join-Path $ServiceDir "logs") | Out-Null
    $p = Start-Process $Java -ArgumentList $jarArgs -WorkingDirectory $ServiceDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ServiceDir "logs\stdout.log") -RedirectStandardError (Join-Path $ServiceDir "logs\stderr.log")
    $p.Id | Out-File -Encoding ascii $PidFile
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $h = Invoke-RestMethod -TimeoutSec 3 http://localhost:8080/actuator/health
            if ($h.status -eq "UP") { Say "服务已启动($Mode,pid=$($p.Id))"; return }
        } catch { }
        Start-Sleep 3
    }
    throw "服务 $HealthTimeoutSeconds 秒内没有 UP,见 $ServiceDir\logs"
}

Set-Location $Repo
$SourceDir = (Resolve-Path $Source).Path
$ReplayDir = (Resolve-Path $Replay).Path
if ($KeyFile) {
    $raw = Get-Content -LiteralPath $KeyFile -Raw
    $m = [regex]::Match($raw, 'sk-[A-Za-z0-9_\-]+')
    $env:LLM_API_KEY = if ($m.Success) { $m.Value } else { $raw.Trim() }
    Remove-Variable raw, m
}
if (-not $env:LLM_API_KEY) { throw "停止条件 1:没有 LLM_API_KEY(给 -KeyFile,或先在当前进程环境里设好)" }
Say ("key 自检:前缀为 sk- = {0},长度 {1}" -f $env:LLM_API_KEY.StartsWith("sk-"), $env:LLM_API_KEY.Length)

$commit = (git -C $Repo rev-parse --short HEAD).Trim()
$dirty = (git -C $Repo status --porcelain -- service | Measure-Object).Count
$ref = "HEAD $commit" + $(if ($dirty) { "(service/ 下有 $dirty 个未提交改动)" } else { "" })

$code = 0
try {
    Stop-TicketService
    if (-not $SkipBuild) {
        Push-Location $ServiceDir
        try {
            & $Maven -o -q -DskipTests package
            if ($LASTEXITCODE -ne 0) { throw "打包失败" }
        } finally { Pop-Location }
    }
    Start-TicketService "real"
    $env:SERVICE_LOG_PATH = Join-Path $ServiceDir "logs\ticket-qa-service.log"
    & $Python $RunEval hybrid $SourceDir $ReplayDir --run-label $RunLabel --service-ref $ref
    $code = $LASTEXITCODE
    Say "run_eval hybrid 退出码 $code(0 = 验证通过并已出报告;4 = 验证不通过;2 = 停止条件)"
}
finally {
    Stop-TicketService
    Remove-Item Env:SERVICE_LOG_PATH -ErrorAction SilentlyContinue
    Start-TicketService "mock"
}
exit $code
