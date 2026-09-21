# WSL2 + Docker Engine:不用 Docker Desktop、不需要管理员的本地环境

适用:Windows 11,当前用户**不是管理员**(装不了 Docker Desktop),但 WSL2 功能已启用。
目标:`docker compose` 起的容器在关掉所有终端之后仍然活着,重启电脑登录后自动回来。

本目录是可复现的全部材料;每一步都在 2026-09-20 实测过,包括三种**不**奏效的方案(见 §4)。

## 1. 一次性安装(重装 / 换机器时照做)

```powershell
# ① 装发行版(用户态,不需要管理员;--web-download 绕过商店)
wsl --install -d Ubuntu-24.04 --web-download --no-launch

# ② 装 Docker Engine + compose 插件(脚本会顺手换阿里云 apt 源、配镜像加速、开 systemd)
wsl -d Ubuntu-24.04 -u root -- bash ops/wsl/wsl-docker-setup.sh      # 在仓库根目录执行;wsl 会把当前目录映射到 /mnt/<盘符>/…

# ③ 发行版配置:systemd 开机拉起 docker(脚本已写,这里是核对)
wsl -d Ubuntu-24.04 -u root -- bash -c 'cat /etc/wsl.conf; systemctl is-enabled docker'
#    期望:[boot] systemd=true  /  enabled

# ④ 虚拟机不自动关机:复制 wslconfig.example 到 %USERPROFILE%\.wslconfig
Copy-Item ops\wsl\wslconfig.example $env:USERPROFILE\.wslconfig

# ⑤ 发行版不自动终止:把 keep-alive 脚本放进当前用户的启动文件夹(登录即生效)
Copy-Item ops\wsl\wsl-keepalive.vbs ([Environment]::GetFolderPath('Startup'))
wscript.exe ops\wsl\wsl-keepalive.vbs      # 本次登录先手动起一次

# ⑥ 让 ④ 生效
wsl --shutdown
```

之后任何时候(仓库根目录):`wsl -d Ubuntu-24.04 -u root -- docker compose --project-directory ops up -d`。
发布的端口在 Windows 侧用 `127.0.0.1:<port>` 直接访问。

## 2. 三层各管什么(为什么缺一不可)

| 层 | 文件 | 管的对象 | 没有它会怎样 |
|---|---|---|---|
| 虚拟机 | `%USERPROFILE%\.wslconfig` → `vmIdleTimeout` | WSL2 底层 utility VM | 所有发行版停掉 60 秒后 VM 关机;下次 `wsl` 命令要冷启动内核,慢几秒 |
| 服务 | `/etc/wsl.conf` → `systemd=true` + `systemctl enable docker` | 发行版启动时拉起 dockerd | 发行版起来了但没有 Docker,得手动 `service docker start` |
| 发行版实例 | 启动文件夹里的 `wsl-keepalive.vbs` | 发行版本身的生命周期 | **最后一个 `wsl.exe` 会话退出后几秒,发行版被终止,容器全部消失,Windows 侧 `Connection refused`** |

第三层是关键,也是最容易误解的:WSL 判断"发行版还有没有人用"只看 **`wsl.exe` 客户端会话**——
systemd 服务、`[boot] command` 拉起的进程都不算。所以必须有一个 Windows 侧的 `wsl.exe` 进程
一直挂着;`wsl-keepalive.vbs` 就是用隐藏窗口挂一个 `wsl.exe -- sleep infinity`。

容器本身靠 compose 里的 `restart: unless-stopped`:发行版重新起来 → systemd 起 docker → docker
把上次没被手动 stop 的容器拉起来。手动 `docker compose stop xxx`(故障注入)的容器不会被拉起,
符合预期。

## 3. 验证方法(照做,每一步都有明确的期望输出)

```powershell
# 关掉所有终端后等 2 分钟,再看:
wsl -l -v                    # Ubuntu-24.04 应为 Running
Test-NetConnection 127.0.0.1 -Port 3306   # TcpTestSucceeded : True

# 模拟重启:强制关 WSL 再拉起
wsl --shutdown
wscript.exe ops\wsl\wsl-keepalive.vbs
Start-Sleep 20
wsl -d Ubuntu-24.04 -u root -- docker ps    # 5 个 ticketqa-* 容器应自动回来
```

2026-09-20 实测:`wsl --shutdown` 后由 keep-alive 拉起,20 秒内 docker active、5 个容器
自动恢复;之后 150 秒无任何会话,发行版仍 Running、3306/6379/5672/8089 全部可连。

## 4. 试过但不奏效的方案(别再走弯路)

| 方案 | 结果 | 原因 |
|---|---|---|
| `.wslconfig` 里 `vmIdleTimeout=-1` | 发行版 150 秒后仍 Stopped | `-1` 不被识别;而且它管的是 VM 不是发行版 |
| `.wslconfig` 里 `vmIdleTimeout=604800000`(单独用) | VM 不关了,发行版照样 Stopped | 发行版终止和 VM 空闲是两套机制 |
| `/etc/wsl.conf` `[boot] command="nohup sleep infinity &"` | 进程在(pid 12),发行版照样 Stopped | boot command 由 init 拉起,不算 `wsl.exe` 客户端会话 |
| 计划任务 `schtasks /Create /SC ONLOGON` | `Access is denied` | 登录触发的计划任务需要管理员;启动文件夹不需要 |
| 手动 `Start-Process wsl.exe ... sleep infinity` | 有效,但注销 / 进程被杀就没了 | 就是第一版联调用的临时方案,现在被启动文件夹取代 |

## 5. 文件清单

| 文件 | 去哪 | 作用 |
|---|---|---|
| `wsl-docker-setup.sh` | 在发行版里以 root 执行一次 | 换 apt 源、装 docker-ce + compose、配镜像加速、写 wsl.conf、enable docker |
| `wsl.conf` | `/etc/wsl.conf` | `systemd=true` |
| `wslconfig.example` | `%USERPROFILE%\.wslconfig` | `vmIdleTimeout` |
| `wsl-keepalive.vbs` | `shell:startup`(`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) | 登录时挂一个隐藏的 `wsl.exe` 会话 |

发行版名 `Ubuntu-24.04` 写死在 `wsl-keepalive.vbs` 和上面的命令里,换名字要一起改。
