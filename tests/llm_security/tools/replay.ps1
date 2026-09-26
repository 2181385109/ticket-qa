# 回放评估(ADR-024 修订 #4):把一次已录制运行里模型的原始输出,经 WireMock 逐条回放给当前工作区的服务。**不发任何真实请求,不需要 API key。**
#
# 本脚本一条命令做完:
#   1. 打包当前工作区的服务(可 -SkipBuild);
#   2. 停掉当前服务(logs/app.pid),以真实模式启动——LLM_BASE_URL 指向 run_eval 起的录制代理,代理的上游是 WireMock 上的回放桩;
#      LLM_API_KEY 给一个占位值(回放桩不校验,也不会有请求离开本机);
#   3. run_eval.py replay <Source>:加载回放桩 → 跑与源运行相同的任务 → 卸载回放桩 → 逐字节比对请求;
#      一致才生成 report.md 与 compare.md(源运行 vs 回放),不一致只写 replay_check.md,退出码 4;
#   4. 无论成败,以挡板模式重启服务(接口自动化默认走挡板)。
#
# 用法(仓库根目录,PowerShell):
#   powershell -ExecutionPolicy Bypass -File tests\llm_security\tools\replay.ps1 `
#       -Source tests\llm_security\reports\phase2-v1-20260926T040541Z -JavaHome D:\tools\jdk-17 -Maven D:\tools\maven\bin\mvn.cmd -Python E:\python\python.exe
# 不要把输出接管道:最后重启的服务进程会继承管道句柄,调用方会一直等(同 holdout_compare.ps1)。要留日志就重定向到文件。
# 只重算验证(不起服务):python tests/llm_security/run_eval.py replay-check <源运行> <回放运行>
param(
    [Parameter(Mandatory)][string]$Source,
    [string]$RunLabel = "v2-replay",
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

function Say($msg) { Write-Host "[replay] $msg" }

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
        $env:LLM_API_KEY = "replay-placeholder-not-a-key"
        # 与源运行相同的评测配置(计划 §4):放宽超时、熔断阈值,写进 meta
        $jarArgs += @('--llm.timeout-ms=30000', '--llm.circuit.failure-threshold=100000')
    } else {
        Remove-Item Env:LLM_BASE_URL -ErrorAction SilentlyContinue
        Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force (Join-Path $ServiceDir "logs") | Out-Null
    $p = Start-Process $Java -ArgumentList $jarArgs -WorkingDirectory $ServiceDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ServiceDir "logs\stdout.log") -RedirectStandardError (Join-Path $ServiceDir "logs\stderr.log")
    $p.Id | Out-File -Encoding ascii $PidFile
    Remove-Item Env:LLM_API_KEY -ErrorAction SilentlyContinue
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
    & $Python $RunEval replay $SourceDir --run-label $RunLabel --service-ref $ref
    $code = $LASTEXITCODE
    Say "run_eval replay 退出码 $code(0 = 请求一致并已出报告;4 = 请求不一致,只出 replay_check.md)"
}
finally {
    Stop-TicketService
    Remove-Item Env:SERVICE_LOG_PATH -ErrorAction SilentlyContinue
    Start-TicketService "mock"
}
exit $code
