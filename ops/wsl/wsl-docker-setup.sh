#!/usr/bin/env bash
# 在 WSL2 Ubuntu 24.04 里安装 Docker Engine + compose 插件(root 运行)。
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "== systemd in wsl.conf"
if ! grep -q "systemd=true" /etc/wsl.conf 2>/dev/null; then
  printf '[boot]\nsystemd=true\n' >> /etc/wsl.conf
  echo "wrote /etc/wsl.conf (needs wsl --shutdown to take effect)"
fi

echo "== apt sources -> aliyun mirror (faster in CN)"
if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then
  sed -i 's|http://archive.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g; s|http://security.ubuntu.com/ubuntu|http://mirrors.aliyun.com/ubuntu|g' /etc/apt/sources.list.d/ubuntu.sources
fi

apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg >/dev/null

echo "== docker apt repo"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null

echo "== docker daemon config"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io"],
  "log-driver": "json-file",
  "log-opts": { "max-size": "20m", "max-file": "3" }
}
JSON

echo "== start docker"
if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running >/dev/null 2>&1; then
  systemctl enable docker >/dev/null 2>&1 || true
  systemctl restart docker
else
  service docker start || (nohup dockerd >/var/log/dockerd.log 2>&1 &)
  sleep 5
fi
docker version
docker compose version
echo "== DONE"
