#!/bin/bash
# Guardian 수집 스크립트. 원격 권한은 건드리지 않는다.
# 모듈이 없거나 명령이 호환되지 않으면 그 항목만 건너뛰고, JSON 한 줄은 무조건 찍는다.
# 같은 JSON 을 OUT_DIR/날짜.json 에도 남긴다. 수집 경로가 비면 스크립트 옆 DailyData/ 이다.
# {{server}} / {{instances}} / {{date}} 는 돌릴 때 서버 값으로 채워진다.
# SEARCH_NAMES 는 플러그인에 적은 검색어(예: qry-api)이며 만들 때 박힌다.
set +e
SERVER_NAME="{{server}}"
INSTANCES="{{instances}}"
SEARCH_NAMES="test check choyoungsang"
DATE="{{date}}"
PLUGIN_NAME="test"
OUT_DIR="__GUARDIAN_COLLECT_PATH__"
[ -z "$DATE" ] || [ "$DATE" = "{{date}}" ] && DATE="$(date +%F)"
if [ -z "$OUT_DIR" ] || [ "$OUT_DIR" = "__GUARDIAN_COLLECT_PATH__" ]; then
  SCRIPT_DIR="."
  if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  fi
  OUT_DIR="$SCRIPT_DIR/DailyData"
fi
WATCH_DIR="${WATCH_DIR:-/var/log}"
TOP_N="${TOP_N:-5}"
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

add_result() {
  local key="$1"
  local body="$2"
  body=$(printf '%s' "$body" | sed 's/":[[:space:]]*,/": null,/g; s/":[[:space:]]*}/": null}/g; s/":[[:space:]]*]/": null]/g')
  case "$body" in
    \{*|\[*) ;;
    *) body='{"status":"unavailable"}' ;;
  esac
  RESULT_BUF="${RESULT_BUF}${key}"$'\t'"${body}"$'\n'
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

check_mem_usage() {
  if have_cmd free; then
    add_result mem_usage "$(free -m | awk '/^Mem:/ {pct=($2>0)?($3*100/$2):0; printf "{\"used_pct\": %.1f, \"used_mb\": %s, \"total_mb\": %s}", pct, $3, $2}')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_usage "$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END {u=t-a; pct=(t>0)?(u*100/t):0; printf "{\"used_pct\": %.1f, \"used_mb\": %.0f, \"total_mb\": %.0f}", pct, u/1024, t/1024}' /proc/meminfo)"
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

check_disk_inode() {
  local rows=""
  if have_cmd df; then
    rows=$(df -Pi 2>/dev/null || df -i 2>/dev/null)
    add_result disk_inode "[$(printf '%s' "$rows" | awk 'NR>1 && $6 ~ /^\// {gsub(/%/,"",$5); if(n++) printf ", "; printf "{\"mount\": \"%s\", \"inode_pct\": %s}", $6, $5}')]"
  else
    add_result disk_inode '{"status":"unavailable"}'
  fi
}

check_disk_dir_size() {
  if have_cmd du && [ -d "$WATCH_DIR" ]; then
    add_result disk_dir_size "$(run_timeout 20 du -sb "$WATCH_DIR" | awk -v p="$WATCH_DIR" '{printf "{\"path\": \"%s\", \"bytes\": %s}", p, $1}')"
  else
    add_result disk_dir_size '{"status":"unavailable"}'
  fi
}

check_net_traffic() {
  if have_cmd ip; then
    add_result net_traffic "[$(ip -s link 2>/dev/null | awk '/^[0-9]+:/{gsub(/:/,"",$2); name=$2} /RX:/{getline; rx=$1} /TX:/{getline; tx=$1; if(name!="" && name!="lo") {if(n++) printf ", "; printf "{\"iface\": \"%s\", \"rx_bytes\": %s, \"tx_bytes\": %s}", name, rx, tx}}')]"
  elif [ -r /proc/net/dev ]; then
    add_result net_traffic "[$(awk -F'[: ]+' 'NR>2 && $1!="lo" {if(n++) printf ", "; printf "{\"iface\": \"%s\", \"rx_bytes\": %s, \"tx_bytes\": %s}", $1, $2, $10}' /proc/net/dev)]"
  else
    add_result net_traffic '{"status":"unavailable"}'
  fi
}

check_net_connections() {
  if have_cmd ss; then
    add_result net_connections "$(ss -s 2>/dev/null | awk '/estab/{e=$2} /TCP:/{tw=$6} END {printf "{\"established\": %s}", e+0}')"
  elif have_cmd netstat; then
    add_result net_connections "$(netstat -ant 2>/dev/null | awk '/ESTABLISHED/{e++} END {printf "{\"established\": %s}", e+0}')"
  else
    add_result net_connections '{"status":"unavailable"}'
  fi
}

check_proc_top_cpu() {
  if have_cmd ps; then
    add_result proc_top_cpu "[$(ps aux 2>/dev/null | awk 'NR>1 {print $3+0 "\t" $4 "\t" $11}' | sort -nr 2>/dev/null | awk -v n="$TOP_N" 'NR<=n {if(i++) printf ", "; gsub(/"/,"",$3); printf "{\"name\": \"%s\", \"cpu_pct\": %s, \"mem_pct\": %s}", $3, $1, $2}')]"
  else
    add_result proc_top_cpu '{"status":"unavailable"}'
  fi
}

check_proc_zombie() {
  if have_cmd ps; then
    add_result proc_zombie "$(ps aux 2>/dev/null | awk '$8 ~ /Z/ {z++} END {printf "{\"count\": %s}", z+0}')"
  else
    add_result proc_zombie '{"status":"unavailable"}'
  fi
}

check_proc_service_alive() {
  local body="" first=1 name ok
  for name in $INSTANCES; do
    [ -z "$name" ] && continue
    ok=false
    if have_cmd systemctl && systemctl is-active --quiet "$name" 2>/dev/null; then
      ok=true
    elif have_cmd pgrep && pgrep -x "$name" >/dev/null 2>&1; then
      ok=true
    elif have_cmd pgrep && pgrep -f "$name" >/dev/null 2>&1; then
      ok=true
    fi
    [ $first -eq 1 ] || body="$body, "
    first=0
    body="$body{\"name\": \"$(json_escape "$name")\", \"ok\": $ok}"
  done
  [ -z "$body" ] && body=""
  add_result proc_service_alive "[$body]"
}

check_os_info() {
  local distro="" kernel=""
  [ -r /etc/os-release ] && distro=$(awk -F= '/^PRETTY_NAME=/{gsub(/"/,"",$2); print $2}' /etc/os-release)
  have_cmd uname && kernel=$(uname -r)
  add_result os_info "$(printf '{"distro": "%s", "kernel": "%s"}' "$(json_escape "$distro")" "$(json_escape "$kernel")")"
}

check_sec_crontab_check() {
  if have_cmd crontab; then
    add_result sec_crontab_check "$(printf '{"lines": %s}' "$(json_num "$(crontab -l 2>/dev/null | awk 'NF && $1!~/^#/{n++} END {print n+0}')")")"
  else
    add_result sec_crontab_check '{"status":"unavailable"}'
  fi
}

check_instance_search() {
  local body="" first=1 name line pid cpu mem cmd ok pids detail
  for name in $SEARCH_NAMES; do
    [ -z "$name" ] && continue
    ok=false
    pid=""
    cpu="0"
    mem="0"
    cmd=""
    pids=0
    detail=""
    if have_cmd ps; then
      line=$(ps aux 2>/dev/null | grep -F -- "$name" | grep -v grep | awk 'NR==1 {print}')
      if [ -n "$line" ]; then
        ok=true
        pid=$(printf '%s' "$line" | awk '{print $2}')
        cpu=$(printf '%s' "$line" | awk '{print $3}')
        mem=$(printf '%s' "$line" | awk '{print $4}')
        cmd=$(printf '%s' "$line" | awk '{for(i=11;i<=NF;i++) printf (i==11?$i:" "$i)}')
      fi
    elif have_cmd pgrep && pgrep -f "$name" >/dev/null 2>&1; then
      ok=true
      pid=$(pgrep -f "$name" | awk 'NR==1 {print}')
    fi
    if [ "$ok" = true ] && [ -n "$pid" ]; then
      pids=1
      detail="pid $pid"
    fi
    [ $first -eq 1 ] || body="$body, "
    first=0
    body="$body{\"name\": \"$(json_escape "$name")\", \"ok\": $ok, \"pid\": \"$(json_escape "$pid")\", \"pids\": $pids, \"cpu_pct\": $cpu, \"mem_pct\": $mem, \"detail\": \"$(json_escape "$detail")\", \"cmd\": \"$(json_escape "$cmd")\"}"
  done
  add_result instance_search "[$body]"
}

# 고른 모듈만 실행. 하나가 깨져도 나머지는 계속 돈다.
run_check check_cpu_usage
run_check check_cpu_load
run_check check_cpu_core_count
run_check check_mem_usage
run_check check_mem_available
run_check check_mem_swap
run_check check_disk_usage
run_check check_disk_inode
run_check check_disk_dir_size
run_check check_net_traffic
run_check check_net_connections
run_check check_proc_top_cpu
run_check check_proc_zombie
run_check check_proc_service_alive
run_check check_os_info
run_check check_sec_crontab_check
run_check check_instance_search

# FOOTER: 모은 것만 JSON 으로 찍는다. 여기까지는 무조건 온다.
cpu_json='{"usage_pct": null}'
mem_json='{"used_pct": null}'
disk_json='[]'
inst_json='[]'
top_json='[]'
extra_parts=""

cpu_usage=$(lookup cpu_usage)
cpu_load=$(lookup cpu_load)
cpu_cores=$(lookup cpu_core_count)
if [ -n "$cpu_usage$cpu_load$cpu_cores" ]; then
  cpu_json=$(printf '{"usage_pct": %s, "load1": %s, "cores": %s}' \
    "$(json_num "$(printf '%s' "$cpu_usage" | sed -n 's/.*"usage_pct":[[:space:]]*\([0-9.]*\).*/\1/p')")" \
    "$(json_num "$(printf '%s' "$cpu_load" | sed -n 's/.*"load1":[[:space:]]*\([0-9.]*\).*/\1/p')")" \
    "$(json_num "$(printf '%s' "$cpu_cores" | sed -n 's/.*"cores":[[:space:]]*\([0-9]*\).*/\1/p')")")
  case "$cpu_json" in \{*) ;; *) cpu_json='{"usage_pct": null}' ;; esac
fi
mem_got=$(lookup mem_usage)
case "$mem_got" in \{*) mem_json=$mem_got ;; esac
disk_got=$(lookup disk_usage)
case "$disk_got" in \[*) disk_json=$disk_got ;; esac
inst_got=$(lookup instance_search)
[ -z "$inst_got" ] && inst_got=$(lookup proc_service_alive)
case "$inst_got" in \[*) inst_json=$inst_got ;; esac
top_got=$(lookup proc_top_cpu)
case "$top_got" in \[*) top_json=$top_got ;; esac

while IFS=$'\t' read -r key body || [ -n "$key" ]; do
  [ -z "$key" ] && continue
  body=$(printf '%s' "$body" | sed 's/":[[:space:]]*,/": null,/g; s/":[[:space:]]*}/": null}/g; s/":[[:space:]]*]/": null]/g')
  case "$body" in \{*|\[*) ;; *) body='{"status":"unavailable"}' ;; esac
  [ -n "$extra_parts" ] && extra_parts="$extra_parts, "
  extra_parts="$extra_parts\"$key\": $body"
done <<RES
${RESULT_BUF}
RES
[ -z "$extra_parts" ] && extra_parts='"empty": true'

JSON_LINE=$(printf '{"server": "%s", "date": "%s", "cpu": %s, "mem": %s, "disk": %s, "instances": %s, "top": %s, "extra": {%s}}' \
  "$(json_escape "$SERVER_NAME")" "$DATE" "$cpu_json" "$mem_json" "$disk_json" "$inst_json" "$top_json" "$extra_parts")
if [ -z "$JSON_LINE" ]; then
  JSON_LINE=$(printf '{"server":"%s","date":"%s","cpu":{"usage_pct":null},"mem":{"used_pct":null},"disk":[],"instances":[],"top":[],"extra":{"status":"partial"}}' \
    "$(json_escape "$SERVER_NAME")" "$DATE")
fi
printf '%s\n' "$JSON_LINE"
mkdir -p "$OUT_DIR" 2>/dev/null
printf '%s\n' "$JSON_LINE" > "$OUT_DIR/${DATE}.json" 2>/dev/null
