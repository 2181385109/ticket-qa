# 留出集:同一组样本分别打"防御前"(tag v0.5-injection-baseline 的服务代码)和"防御后"(当前工作区)的服务,输出对比报告。
#
# 留出集 data/holdout.jsonl 由 data/holdout_source.txt 逐字转换(run_eval.py holdout-convert;来源说明见 tests/llm_security/README.md「留出集」)。
# 本脚本一条命令做完:
#   1. 检查留出集非空、打印调用次数(防御前 + 防御后两次)与预算;
#   2. 停掉当前服务(logs/app.pid);
#   3. 在临时 git worktree 里检出 PreRef,离线打包,以真实模式启动(LLM 指向 run_eval 起的录制代理),跑 run --phase holdout --run-label pre;
#   4. 停掉它,把当前工作区打包,以真实模式启动,跑 --run-label post;
#   5. 停掉它,以挡板模式重启当前服务(接口自动化默认走挡板),删掉临时 worktree;
#   6. run_eval.py compare pre post → holdout-post-*/compare.md。
#
# API key(计划 §2-7):-KeyFile 给出时,只在本脚本这一个进程里把文件内容读进环境变量 LLM_API_KEY(子进程继承),
# 不显示、不写文件、不 setx;自检只输出"前缀是否为 sk-"和长度。不给 -KeyFile 则要求当前环境里已有 LLM_API_KEY。
#
# 用法(仓库根目录,PowerShell):
#   powershell -ExecutionPolicy Bypass -File tests\llm_security\tools\holdout_compare.ps1 -KeyFile '<key 文件路径>' `
#       -JavaHome D:\tools\jdk-17 -Maven D:\tools\maven\bin\mvn.cmd -Python E:\python\python.exe
# 不要把输出接管道(| Select-Object 之类):最后重启的服务进程会继承管道句柄,管道不关,调用方会一直等。要留日志就重定向到文件。
# 冒烟(不读 key、不发请求,只验证 worktree / 打包 / 起停):加 -SmokeTest。
# 中途失败:已完成的那一次运行目录保留;用 run_eval.py run --phase holdout --run-label pre|post --resume <目录> 续跑,
# 最后手动 run_eval.py compare <pre 目录> <post 目录>。
# 防御前那次已经跑完(例如跑完后才失败在后面):加 -PreDir <pre 运行目录>,跳过防御前,只跑防御后并出对比(2026-09-27 加)。
param(
    [string]$KeyFile,
    [int]$K = 5,
    [string]$PreRef = "v0.5-injection-baseline",
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$Maven = "mvn",
    [string]$Python = "python",
    [int]$HealthTimeoutSeconds = 180,
    # 冒烟:不读 key、不发任何真实请求。两版服务都以挡板模式起、查健康、停掉,只验证 worktree / 打包 / 起停这套流程
    [switch]$SmokeTest,
    # 已完成的防御前运行目录:给出时跳过第 1 步(不再打 PreRef 的服务、不再花调用)
    [string]$PreDir
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$RunEval = Join-Path $Repo "tests\llm_security\run_eval.py"
$Reports = Join-Path $Repo "tests\llm_security\reports"
$PidFile = Join-Path $Repo "logs\app.pid"
$Java = if ($JavaHome) { Join-Path $JavaHome "bin\java.exe" } else { "java.exe" }
if ($JavaHome) { $env:JAVA_HOME = $JavaHome }
$Worktree = Join-Path $env:TEMP "ticket-qa-predefense"

function Say($msg) { Write-Host "[holdout] $msg" }

function Invoke-Git([string[]]$Arguments) {
    # PowerShell 5.1 在 Stop 模式下会把原生命令写到 stderr 的进度信息当成异常,这里局部放宽
    $ErrorActionPreference = "Continue"
    & git -C $Repo @Arguments 2>&1 | Out-Null
    return $LASTEXITCODE
}

function Invoke-RunEval([string[]]$Arguments) {
    & $Python $RunEval @Arguments
    if ($LASTEXITCODE -ne 0) { throw "run_eval.py $($Arguments -join ' ') 退出码 $LASTEXITCODE" }
}

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

function Start-TicketService([string]$ServiceDir, [string]$Mode) {
    $env:LLM_MODE = $Mode
    $jarArgs = @('-Dfile.encoding=UTF-8', '-Xms1g', '-Xmx1g', '-XX:+UseG1GC', '-jar', 'target\ticket-qa-service-0.1.0.jar')
    if ($Mode -eq "real") {
        $env:LLM_BASE_URL = "http://127.0.0.1:18090"
        $jarArgs += @('--llm.timeout-ms=30000', '--llm.circuit.failure-threshold=100000')
    } else {
        Remove-Item Env:LLM_BASE_URL -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force (Join-Path $ServiceDir "logs") | Out-Null
    $p = Start-Process $Java -ArgumentList $jarArgs -WorkingDirectory $ServiceDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $ServiceDir "logs\stdout.log") -RedirectStandardError (Join-Path $ServiceDir "logs\stderr.log")
    $p.Id | Out-File -Encoding ascii $PidFile
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $h = Invoke-RestMethod -TimeoutSec 3 http://localhost:8080/actuator/health
            if ($h.status -eq "UP") { Say "服务已启动($Mode,$ServiceDir,pid=$($p.Id))"; return }
        } catch { }
        Start-Sleep 3
    }
    throw "服务 $HealthTimeoutSeconds 秒内没有 UP,见 $ServiceDir\logs"
}

function Build-Jar([string]$ServiceDir) {
    Push-Location $ServiceDir
    try {
        & $Maven -o -q -DskipTests package
        if ($LASTEXITCODE -ne 0) { throw "打包失败:$ServiceDir" }
    } finally { Pop-Location }
}

function Newest-RunDir([string]$Label) {
    Get-ChildItem -Directory -Path $Reports -Filter "holdout-$Label-*" | Sort-Object Name | Select-Object -Last 1
}

function Run-Holdout([string]$Label, [string]$ServiceDir, [string]$Ref) {
    # 录制代理记下的请求才是事实;服务日志只用来核对真实生效的 LLM 配置(run_eval 的 _preflight 读它)
    $env:SERVICE_LOG_PATH = Join-Path $ServiceDir "logs\ticket-qa-service.log"
    Invoke-RunEval @('run', '--phase', 'holdout', '--run-label', $Label, '--k', "$K", '--service-ref', $Ref)
    $d = Newest-RunDir $Label
    if (-not $d) { throw "没找到 holdout-$Label-* 运行目录" }
    Say "$Label 完成:$($d.FullName)"
    return $d.FullName
}

# ------------------------------------------------------------------ 0. 前置检查
Set-Location $Repo
$mode = if ($SmokeTest) { "mock" } else { "real" }
$holdout = Join-Path $Repo "tests\llm_security\data\holdout.jsonl"
if ($SmokeTest) {
    Say "冒烟模式:跳过留出集与 key 检查"
} elseif (-not (Test-Path $holdout) -or -not (Get-Content $holdout | Where-Object { $_.Trim() })) {
    Say "data/holdout.jsonl 为空:没有要跑的样本,退出(未停服务、未发任何请求)"
    exit 0
}
if (-not $SmokeTest) { Invoke-RunEval @('plan', '--holdout', '--k', "$K") }
if ($PreDir) {
    $PreDir = (Resolve-Path $PreDir).Path
    if (-not (Test-Path (Join-Path $PreDir 'raw.jsonl'))) { throw "-PreDir 不是运行目录:$PreDir" }
    Say "跳过防御前:沿用 $PreDir(本次只跑防御后,调用数为上面合计的一半)"
}

if ($SmokeTest) { }
elseif ($KeyFile) {
    $raw = Get-Content -LiteralPath $KeyFile -Raw
    $m = [regex]::Match($raw, 'sk-[A-Za-z0-9_\-]+')
    $env:LLM_API_KEY = if ($m.Success) { $m.Value } else { $raw.Trim() }
    Remove-Variable raw, m
}
if (-not $SmokeTest) {
    if (-not $env:LLM_API_KEY) { throw "停止条件 1:没有 LLM_API_KEY(给 -KeyFile,或先在当前进程环境里设好)" }
    Say ("key 自检:前缀为 sk- = {0},长度 {1}" -f $env:LLM_API_KEY.StartsWith("sk-"), $env:LLM_API_KEY.Length)
}

$preCommit = (git -C $Repo rev-parse --short "$PreRef^{commit}").Trim()
if (-not $preCommit) { throw "找不到 $PreRef" }
$postCommit = (git -C $Repo rev-parse --short HEAD).Trim()
$dirty = (git -C $Repo status --porcelain -- service | Measure-Object).Count
$postRef = "HEAD $postCommit" + $(if ($dirty) { "(service/ 下有 $dirty 个未提交改动)" } else { "" })

$preDir = $PreDir; $postDir = $null
try {
    # ------------------------------------------------------------------ 1. 防御前
    Stop-TicketService
    if (-not $PreDir) {
    if (Test-Path $Worktree) { Invoke-Git @('worktree', 'remove', '--force', $Worktree) | Out-Null; Remove-Item -Recurse -Force $Worktree -ErrorAction SilentlyContinue }
    if ((Invoke-Git @('worktree', 'add', '--detach', $Worktree, $PreRef)) -ne 0) { throw "git worktree add $PreRef 失败" }
    Build-Jar (Join-Path $Worktree "service")
    Start-TicketService (Join-Path $Worktree "service") $mode
    if (-not $SmokeTest) { $preDir = Run-Holdout "pre" (Join-Path $Worktree "service") "$PreRef $preCommit(防御前)" }
    Stop-TicketService
    }

    # ------------------------------------------------------------------ 2. 防御后
    Build-Jar (Join-Path $Repo "service")
    Start-TicketService (Join-Path $Repo "service") $mode
    if (-not $SmokeTest) { $postDir = Run-Holdout "post" (Join-Path $Repo "service") "$postRef(防御后)" }
}
finally {
    Stop-TicketService
    Remove-Item Env:SERVICE_LOG_PATH -ErrorAction SilentlyContinue
    Start-TicketService (Join-Path $Repo "service") "mock"
    if (Test-Path $Worktree) { Invoke-Git @('worktree', 'remove', '--force', $Worktree) | Out-Null }
}
if ($SmokeTest) { Say "冒烟完成:两版服务都能打包、启动、健康检查通过;未发任何真实请求"; exit 0 }

# ------------------------------------------------------------------ 3. 对比
Invoke-RunEval @('compare', $preDir, $postDir)
Say "对比报告:$postDir\compare.md"
Say "C/D 逐条人工核对:两个运行目录里的 holdout_review.csv 骨架已生成,填好核对结论与理由后重新 compare(README「留出集」)"
