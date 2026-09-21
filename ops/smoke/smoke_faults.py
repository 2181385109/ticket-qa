# 联调冒烟脚本(故障注入:依次 stop redis / wiremock / rabbitmq 并观察降级)。需要 docker compose。
# 用法(仓库根目录):python ops/smoke/smoke_faults.py 。正式的故障注入记录按 docs/findings 模板记录。
# Docker 在 WSL2 里时:DOCKER_COMPOSE_CMD="wsl.exe -d Ubuntu-24.04 -u root -- docker compose --project-directory ops"
# (wsl.exe 把当前目录映射到 /mnt/<盘符>/…,相对路径 ops 照样可用)
import json, sys, io, os, shlex, time, subprocess, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE="http://localhost:8080"
DC_CMD=shlex.split(os.environ.get("DOCKER_COMPOSE_CMD") or "docker compose --project-directory ops", posix=False)
def call(method, path, user=None, body=None, label=""):
    h={"Content-Type":"application/json; charset=utf-8"}
    if user is not None: h["X-User-Id"]=str(user)
    data=json.dumps(body,ensure_ascii=False).encode() if body is not None else (b"" if method=="POST" else None)
    req=urllib.request.Request(BASE+path,data=data,headers=h,method=method); t0=time.time()
    try:
        with urllib.request.urlopen(req,timeout=30) as r: st,tx=r.status,r.read().decode()
    except urllib.error.HTTPError as e: st,tx=e.code,e.read().decode()
    js=json.loads(tx) if tx else {}
    print(f"[{label}] {method} {path} -> HTTP {st} code={js.get('code')} {int((time.time()-t0)*1000)}ms | {json.dumps(js.get('data') if js.get('data') is not None else js, ensure_ascii=False)[:140]}")
    return st, js
def dc(*args):
    subprocess.run([*DC_CMD, *args], capture_output=True)
def metric(name):
    with urllib.request.urlopen(BASE+"/actuator/prometheus",timeout=10) as r: txt=r.read().decode()
    return [l.split("}")[-1].strip() if "}" in l else l for l in txt.splitlines() if l.startswith(name)]
def health():
    try:
        with urllib.request.urlopen(BASE+"/actuator/health",timeout=10) as r: st,h=r.status,json.load(r)
    except urllib.error.HTTPError as e: st,h=e.code,json.load(e)   # 有组件 DOWN 时 Actuator 返回 503,正常
    return {"http":st, "overall":h["status"], **{k:v["status"] for k,v in h["components"].items() if k in ("db","redis","rabbit")}}

print("=== R. docker compose stop redis ===")
dc("stop","redis"); time.sleep(3)
print("   health:", health())
call("GET","/api/agents/me",user=3,label="auth with redis down")
st,_=call("POST","/api/admin/sla/scan",user=1,label="sla scan fail-open")
print("   lock_unavailable:", metric("sla_scan_lock_unavailable_total"))
dc("start","redis"); time.sleep(6)
print("   health after restart:", health())
call("GET","/api/agents/me",user=3,label="auth after redis back")

print("\n=== W. docker compose stop wiremock ===")
dc("stop","wiremock"); time.sleep(3)
st,js=call("POST","/api/tickets",user=1,body={"title":"申请退款","content":"x","customerId":6001},label="create with wiremock down -> rules")
print("   fallback UPSTREAM_ERROR:", [m for m in metric("llm_fallback_total") if True][:1], "| category:", js["data"]["category"])
dc("start","wiremock"); time.sleep(8)

print("\n=== Q. docker compose stop rabbitmq ===")
dc("stop","rabbitmq"); time.sleep(3)
print("   health:", health())
tid=js["data"]["id"]
before=metric("mq_event_publish_failed_total")
st,g=call("POST",f"/api/tickets/{tid}/grab",user=3,label="grab with rabbitmq down (must still 200)")
time.sleep(1)
print("   publish_failed before/after:", before, metric("mq_event_publish_failed_total"))
st,a=call("GET",f"/api/tickets/{tid}/audit-logs",user=3,label="audit still written")
print("   audit rows:", len(a["data"]))
dc("start","rabbitmq"); time.sleep(20)
print("   health after restart:", health())
call("POST",f"/api/tickets/{tid}/transitions",user=3,body={"target":"PROCESSING"},label="transition after rabbitmq back")
time.sleep(2)
print("   published/consumed:", metric("mq_event_published_total"), metric("mq_event_consumed_total"))
