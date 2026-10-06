#!/bin/bash
# GoodMorningCheck 수집 스크립트. 원격 권한은 건드리지 않는다.
# 모듈이 없거나 명령이 호환되지 않으면 그 항목만 건너뛰고, JSON 한 줄은 무조건 찍는다.
# 같은 JSON 을 OUT_DIR/날짜.json 에도 남긴다. 수집 경로가 비면 스크립트 옆 DailyData/ 이다.
# {{server}} / {{instances}} / {{date}} 는 돌릴 때 서버 값으로 채워진다.
# SEARCH_NAMES 는 플러그인에 적은 프로세스 이름이며 만들 때 박힌다.
# 실행: bash collect.sh
# 윈도에서 붙여 넣었으면 먼저: sed -i 's/\r$//' collect.sh
if [ -z "${BASH_VERSION:-}" ]; then
  echo "bash collect.sh 로 실행하세요." >&2
  exit 1
fi
_SRC="${BASH_SOURCE[0]:-$0}"
if [ -f "$_SRC" ] && grep -q $'\r' "$_SRC" 2>/dev/null; then
  echo "윈도 줄바꿈(CRLF)입니다. sed -i 's/\\r$//' $_SRC 후 다시 실행하세요." >&2
  exit 1
fi
set +e
export LC_ALL=C
SERVER_NAME="{{server}}"
INSTANCES="{{instances}}"
SEARCH_NAMES=""
DATE="{{date}}"
PLUGIN_NAME="resource_basic"
OUT_DIR="__GUARDIAN_COLLECT_PATH__"
[ -z "$DATE" ] || [ "$DATE" = "{{date}}" ] && DATE="$(date +%F)"
# zip만 반입해서 돌리면 {{server}} 가 그대로다. 그때는 이 서버 호스트 이름을 쓴다.
if [ -z "$SERVER_NAME" ] || [ "$SERVER_NAME" = "{{server}}" ]; then
  SERVER_NAME="$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"
fi
[ "$INSTANCES" = "{{instances}}" ] && INSTANCES=""
[ "$SEARCH_NAMES" = "{{searches}}" ] && SEARCH_NAMES=""
if [ -z "$OUT_DIR" ] || [ "$OUT_DIR" = "__GUARDIAN_COLLECT_PATH__" ]; then
  SCRIPT_DIR="."
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  fi
  OUT_DIR="$SCRIPT_DIR/DailyData"
fi
WATCH_DIR="${WATCH_DIR:-/var/log}"
TOP_N="${TOP_N:-5}"
TAB=$(printf '\t')
RESULT_BUF=""

have_cmd() { command -v "$1" >/dev/null 2>&1; }

run_timeout() {
  local secs="$1"
  shift
  if have_cmd timeout; then
    timeout "$secs" "$@" 2>/dev/null
  else
    "$@" 2>/dev/null
  fi
}

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/	/ /g'
}

json_num() {
  printf '%s' "${1:-}" | awk '
    { gsub(/[[:space:]]/, "", $0) }
    $0 ~ /^-?[0-9]+(\.[0-9]+)?$/ { print $0; found=1 }
    END { if (!found) print "null" }
  '
}

json_join() { printf '%s' "$@"; }

add_result() {
  local key="$1"
  local body="$2"
  body=$(printf '%s' "$body" | sed 's/":[[:space:]]*,/": null,/g; s/":[[:space:]]*}/": null}/g; s/":[[:space:]]*]/": null]/g; s/":[[:space:]]*-[[:space:]]*,/": null,/g; s/":[[:space:]]*-[[:space:]]*}/": null}/g; s/":[[:space:]]*-[[:space:]]*]/": null]/g')
  case "$body" in
    \{*|\[*) ;;
    *) body='{"status":"unavailable"}' ;;
  esac
  RESULT_BUF="${RESULT_BUF}${key}${TAB}${body}"$'\n'
}

lookup() {
  printf '%s' "$RESULT_BUF" | awk -F'\t' -v k="$1" '$1==k {print substr($0, index($0,$2)); exit}'
}

run_check() {
  local fn="$1"
  local key="${fn#check_}"
  "$fn" 2>/dev/null
  if [ -z "$(lookup "$key")" ]; then
    add_result "$key" '{"status":"unavailable"}'
  fi
}

probe_service() {
  local name="$1"
  OK=false
  STARTED_AT=""
  UPTIME_SEC=""
  RESTARTS=0
  PROBLEM=""
  DETAIL=""
  local st="" rst="" ts="" pid=""
  if have_cmd systemctl; then
    st=$(systemctl show -p ActiveState --value "$name" 2>/dev/null || true)
    rst=$(systemctl show -p NRestarts --value "$name" 2>/dev/null || true)
    ts=$(systemctl show -p ActiveEnterTimestamp --value "$name" 2>/dev/null || true)
    case "$st" in
      active) OK=true ;;
      failed) PROBLEM="failed" ;;
      inactive|dead) PROBLEM="stopped" ;;
      "") ;;
      *) PROBLEM="$st" ;;
    esac
    RESTARTS=$(printf '%s' "$rst" | awk '{print $1+0}')
    if [ -n "$ts" ] && [ "$ts" != "n/a" ] && [ "$ts" != "0" ]; then
      STARTED_AT="$ts"
    fi
  fi
  if have_cmd pgrep; then
    pid=$(pgrep -x "$name" 2>/dev/null | awk 'NR==1 {print}')
    [ -z "$pid" ] && pid=$(pgrep -f "$name" 2>/dev/null | awk 'NR==1 {print}')
  fi
    if [ -n "$pid" ]; then
    OK=true
    case "$PROBLEM" in stopped|not_running) PROBLEM="" ;; esac
    DETAIL="pid $pid"
    [ -z "$STARTED_AT" ] && STARTED_AT=$(ps -o lstart= -p "$pid" 2>/dev/null | awk '{$1=$1; print}')
    UPTIME_SEC=$(ps -o etimes= -p "$pid" 2>/dev/null | awk '{print $1+0}')
  fi
  if [ "$OK" != true ] && [ -z "$PROBLEM" ]; then
    PROBLEM="not_running"
  fi
}

instance_json_row() {
  local name="$1"
  json_join '{"name": "' "$(json_escape "$name")" '", "ok": ' "$OK" ', "started_at": "' "$(json_escape "$STARTED_AT")" '", "uptime_sec": ' "$(json_num "$UPTIME_SEC")" ', "restarts": ' "$(json_num "$RESTARTS")" ', "problem": "' "$(json_escape "$PROBLEM")" '", "detail": "' "$(json_escape "$DETAIL")" '"}'
}

check_cpu_usage() {
  local val=""
  if have_cmd mpstat; then
    val=$(run_timeout 8 mpstat 1 1 | awk '/Average/ && /all/ {printf "%.1f", 100-$NF; found=1} END {if (!found) print "0.0"}')
  elif have_cmd top; then
    val=$(run_timeout 8 top -bn1 | awk -F'[, ]+' '/Cpu\(s\)|%Cpu/ {for(i=1;i<=NF;i++) if($i ~ /id/) {printf "%.1f", 100-$(i-1); exit}}')
  fi
  [ -z "$val" ] && { add_result cpu_usage '{"status":"unavailable"}'; return; }
  add_result cpu_usage "$(printf '{"usage_pct": %s}' "$(json_num "$val")")"
}

check_cpu_load() {
  if [ -r /proc/loadavg ]; then
    add_result cpu_load "$(awk '{printf "{\"load1\": %s, \"load5\": %s, \"load15\": %s}", $1, $2, $3}' /proc/loadavg)"
  else
    add_result cpu_load '{"status":"unavailable"}'
  fi
}

check_cpu_core_count() {
  local n=""
  if have_cmd nproc; then
    n=$(nproc 2>/dev/null)
  elif [ -r /proc/cpuinfo ]; then
    n=$(awk '/^processor/{n++} END{print n+0}' /proc/cpuinfo)
  fi
  [ -z "$n" ] && { add_result cpu_core_count '{"status":"unavailable"}'; return; }
  add_result cpu_core_count "$(printf '{"cores": %s}' "$(json_num "$n")")"
}

check_cpu_ctxswitch() {
  if have_cmd vmstat; then
    add_result cpu_ctxswitch "$(run_timeout 8 vmstat 1 2 | awk 'END {printf "{\"cs\": %s, \"in\": %s}", $(NF-1), $(NF-2)}')"
  elif [ -r /proc/stat ]; then
    add_result cpu_ctxswitch "$(awk '/^ctxt/{c=$2} /^intr/{i=$2} END {printf "{\"cs\": %s, \"in\": %s}", c+0, i+0}' /proc/stat)"
  else
    add_result cpu_ctxswitch '{"status":"unavailable"}'
  fi
}

check_mem_usage() {
  if have_cmd free; then
    add_result mem_usage "$(free -m | awk '
      /^Mem:/ { t=$2; avail=$7; if (avail=="") avail=$4; used=t-avail; if (used<0) used=0; pct=(t>0)?(used*100/t):0 }
      /^Swap:/ { st=$2; su=$3; sp=(st>0)?(su*100/st):0 }
      END { printf "{\"used_pct\": %.1f, \"used_mb\": %.0f, \"total_mb\": %.0f, \"available_mb\": %.0f, \"swap_used_pct\": %.1f, \"swap_used_mb\": %.0f, \"swap_total_mb\": %.0f}", pct+0, used+0, t+0, avail+0, sp+0, su+0, st+0 }')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_usage "$(awk '
      /MemTotal/{t=$2} /MemAvailable/{a=$2} /SwapTotal/{st=$2} /SwapFree/{sf=$2}
      END { u=t-a; if (u<0) u=0; pct=(t>0)?(u*100/t):0; su=st-sf; if (su<0) su=0; sp=(st>0)?(su*100/st):0;
        printf "{\"used_pct\": %.1f, \"used_mb\": %.0f, \"total_mb\": %.0f, \"available_mb\": %.0f, \"swap_used_pct\": %.1f, \"swap_used_mb\": %.0f, \"swap_total_mb\": %.0f}", pct, u/1024, t/1024, a/1024, sp, su/1024, st/1024 }' /proc/meminfo)"
  else
    add_result mem_usage '{"status":"unavailable"}'
  fi
}

check_mem_available() {
  if have_cmd free; then
    add_result mem_available "$(free -m | awk '/^Mem:/ {printf "{\"available_mb\": %s}", ($7==""?$4:$7)}')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_available "$(awk '/MemAvailable/{printf "{\"available_mb\": %.0f}", $2/1024}' /proc/meminfo)"
  else
    add_result mem_available '{"status":"unavailable"}'
  fi
}

check_mem_swap() {
  if have_cmd free; then
    add_result mem_swap "$(free -m | awk '/^Swap:/ {pct=($2>0)?($3*100/$2):0; printf "{\"used_pct\": %.1f, \"used_mb\": %s, \"total_mb\": %s}", pct, $3, $2}')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_swap "$(awk '/SwapTotal/{t=$2} /SwapFree/{f=$2} END {u=t-f; pct=(t>0)?(u*100/t):0; printf "{\"used_pct\": %.1f, \"used_mb\": %.0f, \"total_mb\": %.0f}", pct, u/1024, t/1024}' /proc/meminfo)"
  else
    add_result mem_swap '{"status":"unavailable"}'
  fi
}

check_disk_usage() {
  if have_cmd df; then
    add_result disk_usage "[$(df -P -k 2>/dev/null | awk 'NR>1 && $6 ~ /^\// && $2>0 {gsub(/%/,"",$5); if(n++) printf ", "; printf "{\"mount\": \"%s\", \"used_pct\": %s, \"used_gb\": %.1f, \"total_gb\": %.1f, \"free_gb\": %.1f}", $6, $5, $3/1048576, $2/1048576, $4/1048576}')]"
  else
    add_result disk_usage '{"status":"unavailable"}'
  fi
}

check_proc_top_cpu() {
  if have_cmd ps; then
    add_result proc_top_cpu "[$(ps aux 2>/dev/null | awk 'NR>1 {print $3+0 "\t" $4 "\t" $11}' | sort -nr 2>/dev/null | awk -v n="$TOP_N" 'NR<=n {if(i++) printf ", "; gsub(/"/,"",$3); printf "{\"name\": \"%s\", \"cpu_pct\": %s, \"mem_pct\": %s}", $3, $1, $2}')]"
  else
    add_result proc_top_cpu '{"status":"unavailable"}'
  fi
}

check_proc_service_alive() {
  local body="" first=1 name
  for name in $INSTANCES; do
    [ -z "$name" ] && continue
    probe_service "$name"
    [ $first -eq 1 ] || body="$body, "
    first=0
    body="$body$(instance_json_row "$name")"
  done
  add_result proc_service_alive "[$body]"
}

check_net_connections() {
  local src=""
  if have_cmd ss; then
    src=$(ss -tan 2>/dev/null)
  elif have_cmd netstat; then
    src=$(netstat -ant 2>/dev/null)
  else
    add_result net_connections '{"status":"unavailable"}'
    return
  fi
  add_result net_connections "$(printf '%s\n' "$src" | awk '
    BEGIN { est=0; tw=0; cw=0 }
    NR==1 && ($0 ~ /State|Netid|Proto/) { next }
    {
      if ($1 ~ /^(tcp|udp|TCP|UDP)/) { st=toupper($NF); loc=$4; rem=$5 }
      else { st=toupper($1); loc=$4; rem=$5 }
      if (st ~ /ESTAB/) est++
      else if (st ~ /TIME-WAIT|TIME_WAIT/) tw++
      else if (st ~ /CLOSE-WAIT|CLOSE_WAIT/) cw++
      if (st ~ /LISTEN/ || rem=="" || rem=="*" || rem ~ /:\*$/) next
      key=st "\t" loc "\t" rem
      c[key]++
    }
    END {
      printf "{\"established\": %s, \"time_wait\": %s, \"close_wait\": %s, \"peers\": [", est+0, tw+0, cw+0
      n=0
      for (k in c) {
        if (n>=25) break
        split(k, a, "\t")
        if (n++) printf ", "
        gsub(/"/, "", a[1]); gsub(/"/, "", a[2]); gsub(/"/, "", a[3])
        printf "{\"state\": \"%s\", \"local\": \"%s\", \"remote\": \"%s\", \"count\": %s}", a[1], a[2], a[3], c[k]
      }
      printf "]}"
    }')"
}

# 고른 모듈만 실행. 하나가 깨져도 나머지는 계속 돈다.
run_check check_cpu_usage
run_check check_cpu_load
run_check check_cpu_core_count
run_check check_cpu_ctxswitch
run_check check_mem_usage
run_check check_mem_available
run_check check_mem_swap
run_check check_disk_usage
run_check check_proc_top_cpu
run_check check_proc_service_alive
run_check check_net_connections

# FOOTER: 모은 것만 JSON 으로 찍는다. jq 는 쓰지 않는다.
# 셸에서 JSON 을 이어 붙이면 따옴표·% 에 깨지므로, python 이 있으면 dumps, 없으면 awk.
mkdir -p "$OUT_DIR" 2>/dev/null
BUF="$OUT_DIR/.guardian_buf.$$"
printf '%s' "$RESULT_BUF" > "$BUF" 2>/dev/null
JSON_LINE=""

emit_json_python() {
  "$1" - "$SERVER_NAME" "$DATE" "$BUF" 2>/dev/null <<'PY'
import json, sys
server, date, path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    data = open(path, "rb").read()
except Exception:
    data = b""
if sys.version_info[0] >= 3:
    data = data.decode("utf-8", "replace")
extra = {}
for line in data.splitlines():
    if "\t" not in line:
        continue
    key, body = line.split("\t", 1)
    body = body.strip()
    try:
        extra[key] = json.loads(body)
    except Exception:
        extra[key] = {"status": "unavailable"}

def num(block, field):
    if not isinstance(block, dict):
        return None
    val = block.get(field)
    if isinstance(val, bool):
        return None
    try:
        return val + 0
    except Exception:
        return None

cu, cl, cc = extra.get("cpu_usage"), extra.get("cpu_load"), extra.get("cpu_core_count")
cpu = {"usage_pct": num(cu, "usage_pct"), "load1": num(cl, "load1"), "cores": num(cc, "cores")}
mu = extra.get("mem_usage")
if isinstance(mu, dict) and ("used_pct" in mu or "used_mb" in mu):
    mem = mu
else:
    ma, ms = extra.get("mem_available"), extra.get("mem_swap")
    if ma or ms:
        mem = {
            "used_pct": num(ms, "used_pct"),
            "available_mb": num(ma, "available_mb"),
            "swap_used_mb": num(ms, "used_mb"),
            "swap_total_mb": num(ms, "total_mb"),
        }
    else:
        mem = {"used_pct": None}
disk = extra.get("disk_usage")
if not isinstance(disk, list):
    disk = []
inst = extra.get("instance_search")
if not isinstance(inst, list):
    inst = extra.get("proc_service_alive")
if not isinstance(inst, list):
    inst = []
top = extra.get("proc_top_cpu")
if not isinstance(top, list):
    top = []
doc = {"server": server, "date": date, "cpu": cpu, "mem": mem, "disk": disk, "instances": inst, "top": top, "extra": extra}
sys.stdout.write(json.dumps(doc, ensure_ascii=True, separators=(",", ":")) + "\n")
PY
}

if have_cmd python3; then
  JSON_LINE=$(emit_json_python python3)
elif have_cmd python; then
  JSON_LINE=$(emit_json_python python)
fi
JSON_LINE=$(printf '%s' "$JSON_LINE" | tr -d '\r' | awk 'NF{print; exit}')

if [ -z "$JSON_LINE" ]; then
  JSON_LINE=$(GUARDIAN_SERVER="$SERVER_NAME" GUARDIAN_DATE="$DATE" awk '
    BEGIN { server=ENVIRON["GUARDIAN_SERVER"]; date=ENVIRON["GUARDIAN_DATE"] }
    {
      tab = index($0, "\t")
      if (tab < 2) next
      key = substr($0, 1, tab-1)
      body = substr($0, tab+1)
      n++; keys[n]=key; bodies[key]=body
    }
    function nget(s, k,   m) {
      if (s == "") return "null"
      if (match(s, "\"" k "\"[ \t]*:[ \t]*-?[0-9]+(\\.[0-9]+)?")) {
        m = substr(s, RSTART, RLENGTH)
        sub(/^[^:]+:[ \t]*/, "", m)
        return m
      }
      return "null"
    }
    END {
      cpu = "{\"usage_pct\":" nget(bodies["cpu_usage"], "usage_pct") ",\"load1\":" nget(bodies["cpu_load"], "load1") ",\"cores\":" nget(bodies["cpu_core_count"], "cores") "}"
      mem = "{\"used_pct\":" nget(bodies["mem_swap"], "used_pct") ",\"available_mb\":" nget(bodies["mem_available"], "available_mb") ",\"swap_used_mb\":" nget(bodies["mem_swap"], "used_mb") ",\"swap_total_mb\":" nget(bodies["mem_swap"], "total_mb") "}"
      if (bodies["mem_usage"] ~ /^[ \t]*\{/) mem = bodies["mem_usage"]
      disk = "[]"
      if (bodies["disk_usage"] ~ /^[ \t]*\[/) disk = bodies["disk_usage"]
      inst = "[]"
      if (bodies["instance_search"] ~ /^[ \t]*\[/) {
        inst = bodies["instance_search"]
      } else if (bodies["proc_service_alive"] ~ /^[ \t]*\[/) {
        inst = bodies["proc_service_alive"]
      }
      top = "[]"
      if (bodies["proc_top_cpu"] ~ /^[ \t]*\[/) top = bodies["proc_top_cpu"]
      extra = ""
      for (i = 1; i <= n; i++) {
        k = keys[i]; b = bodies[k]
        if (b !~ /^[ \t]*[\{\[]/) b = "{\"status\":\"unavailable\"}"
        if (extra != "") extra = extra ","
        extra = extra "\"" k "\":" b
      }
      if (extra == "") extra = "\"empty\":true"
      gsub(/\\/, "\\\\", server); gsub(/"/, "\\\"", server)
      printf "{\"server\":\"%s\",\"date\":\"%s\",\"cpu\":%s,\"mem\":%s,\"disk\":%s,\"instances\":%s,\"top\":%s,\"extra\":{%s}}\n", server, date, cpu, mem, disk, inst, top, extra
    }
  ' "$BUF" 2>/dev/null)
fi
rm -f "$BUF" 2>/dev/null
if [ -z "$JSON_LINE" ]; then
  JSON_LINE="{\"server\":\"\",\"date\":\"$DATE\",\"cpu\":{\"usage_pct\":null},\"mem\":{\"used_pct\":null},\"disk\":[],\"instances\":[],\"top\":[],\"extra\":{\"status\":\"partial\"}}"
fi
printf '%s\n' "$JSON_LINE"
printf '%s\n' "$JSON_LINE" > "$OUT_DIR/${DATE}.json" 2>/dev/null
