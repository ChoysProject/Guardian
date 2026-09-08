"""체크한 수집 모듈로 원격 셸 스크립트 뼈대를 만든다."""
from __future__ import annotations

import re
from typing import Any

_SEARCH_NAME = re.compile(r"^[A-Za-z0-9._:-]+$")
DATA_FOLDER = "DailyData"

CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "cpu",
        "name": "CPU",
        "modules": [
            {"id": "cpu_usage", "name": "CPU 사용률", "desc": "전체 CPU 사용률(%)", "help": "지금 CPU가 얼마나 바쁜지 봅니다. mpstat가 있으면 그걸 쓰고, 없으면 top으로 잽니다. 둘 다 없으면 이 칸만 비웁니다.", "primary": "mpstat 1 1", "fallback": "top -bn1", "commands": ["mpstat", "top"], "default": True},
            {"id": "cpu_load", "name": "Load Average", "desc": "1/5/15분 부하", "help": "최근 1·5·15분 동안 할 일이 얼마나 쌓였는지 봅니다. /proc/loadavg를 읽습니다.", "primary": "cat /proc/loadavg", "fallback": "-", "commands": [], "default": True},
            {"id": "cpu_core_count", "name": "코어 개수", "desc": "논리 코어 수", "help": "CPU 코어가 몇 개인지 봅니다. nproc가 없으면 /proc/cpuinfo에서 셉니다.", "primary": "nproc", "fallback": "/proc/cpuinfo", "commands": ["nproc"], "default": True},
            {"id": "cpu_steal", "name": "Steal Time", "desc": "클라우드 VM 리소스 뺏김 여부", "help": "클라우드에서 다른 가상머신이 CPU를 얼마나 빼앗아 갔는지 봅니다. mpstat가 없으면 건너뜁니다.", "primary": "mpstat 1 1 (%steal)", "fallback": "N/A", "commands": ["mpstat"], "default": False},
            {"id": "cpu_ctxswitch", "name": "Context Switch/Interrupt", "desc": "과도한 스위칭 여부", "help": "프로세스 전환이 너무 잦은지 봅니다. vmstat를 쓰고, 없으면 /proc/stat을 봅니다.", "primary": "vmstat 1 2", "fallback": "/proc/stat", "commands": ["vmstat"], "default": False},
        ],
    },
    {
        "id": "memory",
        "name": "Memory",
        "modules": [
            {"id": "mem_usage", "name": "메모리 사용률", "desc": "전체 사용량/사용률", "help": "메모리를 몇 % 쓰는지 봅니다. free를 쓰고, 없으면 /proc/meminfo를 봅니다.", "primary": "free -m", "fallback": "/proc/meminfo", "commands": ["free"], "default": True},
            {"id": "mem_available", "name": "Available 메모리", "desc": "캐시 제외 실질 가용량", "help": "지금 바로 쓸 수 있는 여유 메모리입니다. 캐시까지 감안한 값이라 사용률보다 실제 여유에 가깝습니다.", "primary": "free -m (available)", "fallback": "/proc/meminfo", "commands": ["free"], "default": True},
            {"id": "mem_swap", "name": "Swap 사용량", "desc": "Swap 사용 여부/비율", "help": "메모리가 부족해 디스크로 넘긴 양입니다. 값이 오르면 서버가 느려질 수 있습니다.", "primary": "free -m", "fallback": "/proc/meminfo", "commands": ["free"], "default": True},
            {"id": "mem_oom", "name": "OOM Killer 이력", "desc": "최근 OOM 발생 여부", "help": "메모리 부족으로 프로세스가 강제로 죽은 적이 있는지 봅니다. dmesg/journal 권한이 없으면 이 칸만 비울 수 있습니다.", "primary": "dmesg -T", "fallback": "journalctl -k", "commands": ["dmesg", "journalctl"], "default": False},
        ],
    },
    {
        "id": "disk",
        "name": "Disk",
        "modules": [
            {"id": "disk_usage", "name": "디스크 사용률", "desc": "마운트별 사용률(%)", "help": "디스크가 마운트마다 얼마나 찼는지 봅니다. df로 읽습니다. WSL에서는 윈도 드라이브도 같이 나올 수 있습니다.", "primary": "df -hT", "fallback": "df -h", "commands": ["df"], "default": True},
            {"id": "disk_inode", "name": "inode 사용률", "desc": "inode 고갈 여부", "help": "파일 개수 한도가 바닥났는지 봅니다. 용량은 남았는데 파일을 못 만들 때 이 값을 봅니다.", "primary": "df -i", "fallback": "N/A", "commands": ["df"], "default": False},
            {"id": "disk_iowait", "name": "I/O Wait", "desc": "CPU의 디스크 대기시간(%)", "help": "CPU가 디스크 응답을 기다리며 논 비율입니다. iostat가 있으면 그걸 쓰고, 없으면 vmstat을 봅니다.", "primary": "iostat -x 1 2", "fallback": "vmstat wa", "commands": ["iostat", "vmstat"], "default": False},
            {"id": "disk_iops", "name": "디스크 처리량/IOPS", "desc": "read/write 처리량", "help": "디스크가 얼마나 읽고 썼는지 봅니다. iostat가 없으면 /proc/diskstats를 봅니다.", "primary": "iostat -x 1 2", "fallback": "/proc/diskstats", "commands": ["iostat"], "default": False},
            {"id": "disk_dir_size", "name": "특정 디렉토리 용량", "desc": "로그 등 지정 경로 용량 추적", "help": "지정한 폴더(기본 /var/log)가 얼마나 큰지 봅니다. 폴더가 크면 조금 오래 걸릴 수 있습니다.", "primary": "du -sh <path>", "fallback": "동일", "commands": ["du"], "default": False},
        ],
    },
    {
        "id": "network",
        "name": "Network",
        "modules": [
            {"id": "net_traffic", "name": "RX/TX 트래픽", "desc": "인터페이스별 송수신량", "help": "각 네트워크 카드가 받고 보낸 총량입니다. ip가 없으면 /proc/net/dev를 봅니다.", "primary": "ip -s link", "fallback": "/proc/net/dev", "commands": ["ip"], "default": False},
            {"id": "net_connections", "name": "연결 상태 수", "desc": "ESTABLISHED/TIME_WAIT 등", "help": "지금 열려 있는 TCP 연결 수입니다. ss를 쓰고, 없으면 netstat을 씁니다.", "primary": "ss -s", "fallback": "netstat -s", "commands": ["ss", "netstat"], "default": False},
            {"id": "net_errors", "name": "패킷 드랍/에러", "desc": "NIC 레벨 오류", "help": "패킷이 버려지거나 깨진 횟수입니다. 네트워크 카드 이상을 의심할 때 킵니다.", "primary": "ip -s link", "fallback": "/proc/net/dev", "commands": ["ip"], "default": False},
            {"id": "net_listen_ports", "name": "리스닝 포트 목록", "desc": "열린 포트/서비스", "help": "밖에서 들어올 수 있게 열려 있는 포트 목록입니다. ss 또는 netstat이 필요합니다.", "primary": "ss -tulnp", "fallback": "netstat -tulnp", "commands": ["ss", "netstat"], "default": False},
        ],
    },
    {
        "id": "process",
        "name": "Process / Application",
        "modules": [
            {"id": "proc_top_cpu", "name": "CPU 상위 프로세스", "desc": "CPU 기준 Top N", "help": "CPU를 많이 쓰는 프로세스 위쪽 몇 개를 남깁니다. 누가 바쁜지 볼 때 씁니다.", "primary": "ps aux --sort=-%cpu", "fallback": "동일", "commands": ["ps"], "default": True},
            {"id": "proc_top_mem", "name": "메모리 상위 프로세스", "desc": "메모리 기준 Top N", "help": "메모리를 많이 쓰는 프로세스 위쪽 몇 개를 남깁니다.", "primary": "ps aux --sort=-%mem", "fallback": "동일", "commands": ["ps"], "default": False},
            {"id": "proc_zombie", "name": "좀비 프로세스", "desc": "좀비 상태 프로세스 수", "help": "이미 끝났는데 부모가 거두지 않은 프로세스 개수입니다. 많으면 부모 프로세스를 의심합니다.", "primary": "ps aux", "fallback": "동일", "commands": ["ps"], "default": False},
            {"id": "proc_service_alive", "name": "서비스 생존 확인", "desc": "지정 서비스명 실행 여부", "help": "적어 둔 이름이 살아 있는지 봅니다. systemd 서비스면 systemctl, 아니면 프로세스 이름으로 찾습니다.", "primary": "systemctl is-active", "fallback": "pgrep -x", "commands": ["systemctl", "pgrep"], "default": True},
            {"id": "proc_fd_usage", "name": "파일 디스크립터 사용량", "desc": "fd 사용량/한도 대비", "help": "열린 파일·소켓이 얼마나 많은지 봅니다. lsof가 없으면 이 스크립트 자신의 개수만 셉니다.", "primary": "lsof | wc -l", "fallback": "/proc/<pid>/fd", "commands": ["lsof"], "default": False},
        ],
    },
    {
        "id": "os",
        "name": "Instance / OS",
        "modules": [
            {"id": "os_info", "name": "OS/커널 버전", "desc": "배포판, 커널 버전", "help": "어떤 리눅스인지, 커널이 무엇인지를 남깁니다. /etc/os-release와 uname을 읽습니다.", "primary": "cat /etc/os-release, uname -r", "fallback": "N/A", "commands": ["uname"], "default": False},
            {"id": "os_uptime", "name": "Uptime", "desc": "마지막 부팅 시각", "help": "마지막으로 재부팅한 시각입니다. 갑자기 바뀌면 재시작이 있었던 겁니다.", "primary": "uptime -s", "fallback": "who -b", "commands": ["uptime", "who"], "default": False},
            {"id": "os_cloud_meta", "name": "클라우드 인스턴스 정보", "desc": "인스턴스 타입 등 (AWS 기준)", "help": "AWS 인스턴스 타입만 봅니다. 클라우드가 아니면 건너뜁니다.", "primary": "curl 169.254.169.254", "fallback": "온프렘이면 스킵", "commands": ["curl"], "default": False},
            {"id": "os_ntp_sync", "name": "시간 동기화 상태", "desc": "NTP drift 여부", "help": "서버 시간이 NTP와 맞는지 봅니다. 시간이 틀리면 로그·인증이 꼬일 수 있습니다.", "primary": "timedatectl status", "fallback": "ntpq -p", "commands": ["timedatectl", "ntpq"], "default": False},
        ],
    },
    {
        "id": "security",
        "name": "보안/이상행위 (기본 비활성)",
        "security": True,
        "modules": [
            {"id": "sec_failed_login", "name": "로그인 실패 이력", "desc": "최근 실패 로그인 시도", "help": "최근 로그인 실패가 몇 번인지 봅니다. lastb가 없거나 권한이 없으면 이 칸은 비울 수 있습니다.", "primary": "lastb", "fallback": "N/A", "commands": ["lastb"], "default": False, "security": True},
            {"id": "sec_crontab_check", "name": "crontab 변경 확인", "desc": "사용자별 crontab 조회", "help": "지금 계정 crontab에 줄이 몇 개인지 봅니다. 다른 사용자 것은 보지 않습니다.", "primary": "crontab -l", "fallback": "N/A", "commands": ["crontab"], "default": False, "security": True},
        ],
    },
]

HEADER = r'''#!/bin/bash
# Guardian 수집 스크립트. 원격 권한은 건드리지 않는다.
# 모듈이 없거나 명령이 호환되지 않으면 그 항목만 건너뛰고, JSON 한 줄은 무조건 찍는다.
# 같은 JSON 을 OUT_DIR/날짜.json 에도 남긴다. 수집 경로가 비면 스크립트 옆 DailyData/ 이다.
# {{server}} / {{instances}} / {{date}} 는 돌릴 때 서버 값으로 채워진다.
# SEARCH_NAMES 는 플러그인에 적은 검색어(예: qry-api)이며 만들 때 박힌다.
set +e
SERVER_NAME="{{server}}"
INSTANCES="{{instances}}"
SEARCH_NAMES="{{searches}}"
DATE="{{date}}"
PLUGIN_NAME="{{plugin}}"
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
'''

FOOTER = r'''
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
'''

MODULES: dict[str, str] = {
    "cpu_usage": r'''
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
''',
    "cpu_load": r'''
check_cpu_load() {
  if [ -r /proc/loadavg ]; then
    add_result cpu_load "$(awk '{printf "{\"load1\": %s, \"load5\": %s, \"load15\": %s}", $1, $2, $3}' /proc/loadavg)"
  else
    add_result cpu_load '{"status":"unavailable"}'
  fi
}
''',
    "cpu_core_count": r'''
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
''',
    "cpu_steal": r'''
check_cpu_steal() {
  if have_cmd mpstat; then
    add_result cpu_steal "$(run_timeout 8 mpstat 1 1 | awk '/Average/ && /all/ {printf "{\"steal_pct\": %s}", $(NF-1)}')"
  else
    add_result cpu_steal '{"status":"unavailable"}'
  fi
}
''',
    "cpu_ctxswitch": r'''
check_cpu_ctxswitch() {
  if have_cmd vmstat; then
    add_result cpu_ctxswitch "$(run_timeout 8 vmstat 1 2 | awk 'END {printf "{\"cs\": %s, \"in\": %s}", $(NF-1), $(NF-2)}')"
  elif [ -r /proc/stat ]; then
    add_result cpu_ctxswitch "$(awk '/^ctxt/{c=$2} /^intr/{i=$2} END {printf "{\"cs\": %s, \"in\": %s}", c+0, i+0}' /proc/stat)"
  else
    add_result cpu_ctxswitch '{"status":"unavailable"}'
  fi
}
''',
    "mem_usage": r'''
check_mem_usage() {
  if have_cmd free; then
    add_result mem_usage "$(free -m | awk '/^Mem:/ {pct=($2>0)?($3*100/$2):0; printf "{\"used_pct\": %.1f, \"used_mb\": %s, \"total_mb\": %s}", pct, $3, $2}')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_usage "$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END {u=t-a; pct=(t>0)?(u*100/t):0; printf "{\"used_pct\": %.1f, \"used_mb\": %.0f, \"total_mb\": %.0f}", pct, u/1024, t/1024}' /proc/meminfo)"
  else
    add_result mem_usage '{"status":"unavailable"}'
  fi
}
''',
    "mem_available": r'''
check_mem_available() {
  if have_cmd free; then
    add_result mem_available "$(free -m | awk '/^Mem:/ {printf "{\"available_mb\": %s}", ($7==""?$4:$7)}')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_available "$(awk '/MemAvailable/{printf "{\"available_mb\": %.0f}", $2/1024}' /proc/meminfo)"
  else
    add_result mem_available '{"status":"unavailable"}'
  fi
}
''',
    "mem_swap": r'''
check_mem_swap() {
  if have_cmd free; then
    add_result mem_swap "$(free -m | awk '/^Swap:/ {pct=($2>0)?($3*100/$2):0; printf "{\"used_pct\": %.1f, \"used_mb\": %s, \"total_mb\": %s}", pct, $3, $2}')"
  elif [ -r /proc/meminfo ]; then
    add_result mem_swap "$(awk '/SwapTotal/{t=$2} /SwapFree/{f=$2} END {u=t-f; pct=(t>0)?(u*100/t):0; printf "{\"used_pct\": %.1f, \"used_mb\": %.0f, \"total_mb\": %.0f}", pct, u/1024, t/1024}' /proc/meminfo)"
  else
    add_result mem_swap '{"status":"unavailable"}'
  fi
}
''',
    "mem_oom": r'''
check_mem_oom() {
  local hit=""
  if have_cmd dmesg; then
    hit=$(run_timeout 6 dmesg -T 2>/dev/null | grep -ci 'Out of memory\|oom-kill' || true)
  elif have_cmd journalctl; then
    hit=$(run_timeout 6 journalctl -k -n 200 --no-pager 2>/dev/null | grep -ci 'Out of memory\|oom-kill' || true)
  fi
  [ -z "$hit" ] && { add_result mem_oom '{"status":"unavailable"}'; return; }
  add_result mem_oom "$(printf '{"hits": %s}' "$(json_num "$hit")")"
}
''',
    "disk_usage": r'''
check_disk_usage() {
  if have_cmd df; then
    add_result disk_usage "[$(df -P -k 2>/dev/null | awk 'NR>1 && $6 ~ /^\// && $2>0 {gsub(/%/,"",$5); if(n++) printf ", "; printf "{\"mount\": \"%s\", \"used_pct\": %s, \"used_gb\": %.1f, \"total_gb\": %.1f, \"free_gb\": %.1f}", $6, $5, $3/1048576, $2/1048576, $4/1048576}')]"
  else
    add_result disk_usage '{"status":"unavailable"}'
  fi
}
''',
    "disk_inode": r'''
check_disk_inode() {
  local rows=""
  if have_cmd df; then
    rows=$(df -Pi 2>/dev/null || df -i 2>/dev/null)
    add_result disk_inode "[$(printf '%s' "$rows" | awk 'NR>1 && $6 ~ /^\// {gsub(/%/,"",$5); if(n++) printf ", "; printf "{\"mount\": \"%s\", \"inode_pct\": %s}", $6, $5}')]"
  else
    add_result disk_inode '{"status":"unavailable"}'
  fi
}
''',
    "disk_iowait": r'''
check_disk_iowait() {
  if have_cmd iostat; then
    add_result disk_iowait "$(run_timeout 8 iostat -c 1 2 | awk '/^avg-cpu/ {getline; printf "{\"iowait_pct\": %s}", $4}')"
  elif have_cmd vmstat; then
    add_result disk_iowait "$(run_timeout 8 vmstat 1 2 | awk 'END {printf "{\"iowait_pct\": %s}", $16}')"
  else
    add_result disk_iowait '{"status":"unavailable"}'
  fi
}
''',
    "disk_iops": r'''
check_disk_iops() {
  if have_cmd iostat; then
    add_result disk_iops "[$(run_timeout 8 iostat -x 1 2 | awk 'NF>10 && $1!="Device" && $1!~/^Linux/ && $1!~/^avg/ {if(n++) printf ", "; printf "{\"device\": \"%s\", \"r_s\": %s, \"w_s\": %s}", $1, $4, $5}')]"
  elif [ -r /proc/diskstats ]; then
    add_result disk_iops "[$(awk 'NF>=14 && $3 !~ /loop|ram/ {if(n++) printf ", "; printf "{\"device\": \"%s\", \"reads\": %s, \"writes\": %s}", $3, $4, $8}' /proc/diskstats)]"
  else
    add_result disk_iops '{"status":"unavailable"}'
  fi
}
''',
    "disk_dir_size": r'''
check_disk_dir_size() {
  if have_cmd du && [ -d "$WATCH_DIR" ]; then
    add_result disk_dir_size "$(run_timeout 20 du -sb "$WATCH_DIR" | awk -v p="$WATCH_DIR" '{printf "{\"path\": \"%s\", \"bytes\": %s}", p, $1}')"
  else
    add_result disk_dir_size '{"status":"unavailable"}'
  fi
}
''',
    "net_traffic": r'''
check_net_traffic() {
  if have_cmd ip; then
    add_result net_traffic "[$(ip -s link 2>/dev/null | awk '/^[0-9]+:/{gsub(/:/,"",$2); name=$2} /RX:/{getline; rx=$1} /TX:/{getline; tx=$1; if(name!="" && name!="lo") {if(n++) printf ", "; printf "{\"iface\": \"%s\", \"rx_bytes\": %s, \"tx_bytes\": %s}", name, rx, tx}}')]"
  elif [ -r /proc/net/dev ]; then
    add_result net_traffic "[$(awk -F'[: ]+' 'NR>2 && $1!="lo" {if(n++) printf ", "; printf "{\"iface\": \"%s\", \"rx_bytes\": %s, \"tx_bytes\": %s}", $1, $2, $10}' /proc/net/dev)]"
  else
    add_result net_traffic '{"status":"unavailable"}'
  fi
}
''',
    "net_connections": r'''
check_net_connections() {
  if have_cmd ss; then
    add_result net_connections "$(ss -s 2>/dev/null | awk '/estab/{e=$2} /TCP:/{tw=$6} END {printf "{\"established\": %s}", e+0}')"
  elif have_cmd netstat; then
    add_result net_connections "$(netstat -ant 2>/dev/null | awk '/ESTABLISHED/{e++} END {printf "{\"established\": %s}", e+0}')"
  else
    add_result net_connections '{"status":"unavailable"}'
  fi
}
''',
    "net_errors": r'''
check_net_errors() {
  if [ -r /proc/net/dev ]; then
    add_result net_errors "[$(awk -F'[: ]+' 'NR>2 && $1!="lo" {if(n++) printf ", "; printf "{\"iface\": \"%s\", \"rx_drop\": %s, \"tx_drop\": %s, \"rx_err\": %s, \"tx_err\": %s}", $1, $5, $13, $4, $12}' /proc/net/dev)]"
  else
    add_result net_errors '{"status":"unavailable"}'
  fi
}
''',
    "net_listen_ports": r'''
check_net_listen_ports() {
  if have_cmd ss; then
    add_result net_listen_ports "[$(ss -tuln 2>/dev/null | awk 'NR>1 {if(n++) printf ", "; printf "{\"proto\": \"%s\", \"local\": \"%s\"}", $1, $5}')]"
  elif have_cmd netstat; then
    add_result net_listen_ports "[$(netstat -tuln 2>/dev/null | awk '/LISTEN|udp/ {if(n++) printf ", "; printf "{\"proto\": \"%s\", \"local\": \"%s\"}", $1, $4}')]"
  else
    add_result net_listen_ports '{"status":"unavailable"}'
  fi
}
''',
    "proc_top_cpu": r'''
check_proc_top_cpu() {
  if have_cmd ps; then
    add_result proc_top_cpu "[$(ps aux 2>/dev/null | awk 'NR>1 {print $3+0 "\t" $4 "\t" $11}' | sort -nr 2>/dev/null | awk -v n="$TOP_N" 'NR<=n {if(i++) printf ", "; gsub(/"/,"",$3); printf "{\"name\": \"%s\", \"cpu_pct\": %s, \"mem_pct\": %s}", $3, $1, $2}')]"
  else
    add_result proc_top_cpu '{"status":"unavailable"}'
  fi
}
''',
    "proc_top_mem": r'''
check_proc_top_mem() {
  if have_cmd ps; then
    add_result proc_top_mem "[$(ps aux 2>/dev/null | awk 'NR>1 {print $4+0 "\t" $3 "\t" $11}' | sort -nr 2>/dev/null | awk -v n="$TOP_N" 'NR<=n {if(i++) printf ", "; gsub(/"/,"",$3); printf "{\"name\": \"%s\", \"cpu_pct\": %s, \"mem_pct\": %s}", $3, $2, $1}')]"
  else
    add_result proc_top_mem '{"status":"unavailable"}'
  fi
}
''',
    "proc_zombie": r'''
check_proc_zombie() {
  if have_cmd ps; then
    add_result proc_zombie "$(ps aux 2>/dev/null | awk '$8 ~ /Z/ {z++} END {printf "{\"count\": %s}", z+0}')"
  else
    add_result proc_zombie '{"status":"unavailable"}'
  fi
}
''',
    "proc_service_alive": r'''
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
''',
    "proc_fd_usage": r'''
check_proc_fd_usage() {
  if have_cmd lsof; then
    add_result proc_fd_usage "$(printf '{"open": %s}' "$(json_num "$(run_timeout 15 lsof 2>/dev/null | wc -l)")")"
  elif [ -d /proc/$$/fd ]; then
    add_result proc_fd_usage "$(printf '{"open": %s}' "$(json_num "$(ls /proc/$$/fd 2>/dev/null | wc -l)")")"
  else
    add_result proc_fd_usage '{"status":"unavailable"}'
  fi
}
''',
    "os_info": r'''
check_os_info() {
  local distro="" kernel=""
  [ -r /etc/os-release ] && distro=$(awk -F= '/^PRETTY_NAME=/{gsub(/"/,"",$2); print $2}' /etc/os-release)
  have_cmd uname && kernel=$(uname -r)
  add_result os_info "$(printf '{"distro": "%s", "kernel": "%s"}' "$(json_escape "$distro")" "$(json_escape "$kernel")")"
}
''',
    "os_uptime": r'''
check_os_uptime() {
  local since=""
  if have_cmd uptime && uptime -s >/dev/null 2>&1; then
    since=$(uptime -s)
  elif have_cmd who; then
    since=$(who -b 2>/dev/null | awk '{print $3" "$4}')
  fi
  [ -z "$since" ] && { add_result os_uptime '{"status":"unavailable"}'; return; }
  add_result os_uptime "$(printf '{"since": "%s"}' "$(json_escape "$since")")"
}
''',
    "os_cloud_meta": r'''
check_os_cloud_meta() {
  local itype=""
  if have_cmd curl; then
    itype=$(run_timeout 2 curl -s http://169.254.169.254/latest/meta-data/instance-type || true)
  fi
  [ -z "$itype" ] && { add_result os_cloud_meta '{"status":"skipped"}'; return; }
  add_result os_cloud_meta "$(printf '{"instance_type": "%s"}' "$(json_escape "$itype")")"
}
''',
    "os_ntp_sync": r'''
check_os_ntp_sync() {
  if have_cmd timedatectl; then
    add_result os_ntp_sync "$(timedatectl status 2>/dev/null | awk -F': ' '/synchronized/{gsub(/ /,"",$2); printf "{\"ntp_synchronized\": %s}", ($2=="yes")?"true":"false"}')"
  elif have_cmd ntpq; then
    add_result os_ntp_sync '{"ntp_synchronized": true}'
  else
    add_result os_ntp_sync '{"status":"unavailable"}'
  fi
}
''',
    "sec_failed_login": r'''
check_sec_failed_login() {
  if have_cmd lastb; then
    add_result sec_failed_login "$(printf '{"count": %s}' "$(json_num "$(run_timeout 8 lastb -n 50 2>/dev/null | awk 'NF && $1!=\"btmp\" {n++} END {print n+0}')")")"
  else
    add_result sec_failed_login '{"status":"unavailable"}'
  fi
}
''',
    "sec_crontab_check": r'''
check_sec_crontab_check() {
  if have_cmd crontab; then
    add_result sec_crontab_check "$(printf '{"lines": %s}' "$(json_num "$(crontab -l 2>/dev/null | awk 'NF && $1!~/^#/{n++} END {print n+0}')")")"
  else
    add_result sec_crontab_check '{"status":"unavailable"}'
  fi
}
''',
}


def catalog() -> list[dict[str, Any]]:
    return CATEGORIES


def default_modules() -> list[str]:
    names = []
    for group in CATEGORIES:
        for item in group["modules"]:
            if item.get("default"):
                names.append(item["id"])
    return names


def all_module_ids() -> set[str]:
    return {item["id"] for group in CATEGORIES for item in group["modules"]}


def module_by_id(module_id: str) -> dict[str, Any] | None:
    for group in CATEGORIES:
        for item in group["modules"]:
            if item["id"] == module_id:
                return item
    return None


INSTANCE_SEARCH = r'''
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
'''


def parse_denied(raw: str | list[str] | None) -> list[str]:
    if isinstance(raw, list):
        parts = raw
    else:
        parts = (raw or "").replace(",", " ").split()
    cleaned = []
    for item in parts:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def clean_search_names(raw: list[str] | str | None) -> list[str]:
    if isinstance(raw, str):
        parts = raw.replace(",", " ").split()
    else:
        parts = raw or []
    cleaned = []
    for item in parts:
        text = str(item or "").strip()
        if text and text not in cleaned and _SEARCH_NAME.fullmatch(text):
            cleaned.append(text)
    return cleaned


def select_modules(chosen: list[str] | None, denied: list[str] | None = None) -> tuple[list[str], list[str]]:
    known = all_module_ids()
    wanted = [name for name in (chosen or []) if name in known]
    if not wanted:
        wanted = default_modules()
    blocked = []
    kept = []
    deny = {item.lower() for item in (denied or [])}
    for name in wanted:
        spec = module_by_id(name) or {}
        hit = next((cmd for cmd in spec.get("commands") or [] if cmd.lower() in deny), "")
        if hit:
            blocked.append(f"{name}: 금지 명령어 {hit}")
            continue
        kept.append(name)
    return kept, blocked


def script_folder_name(name: str | None) -> str:
    raw = (name or "").strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
    return safe or "resource"


def build_script(
    chosen: list[str] | None = None,
    denied: list[str] | str | None = None,
    instances: list[str] | str | None = None,
    plugin_name: str | None = None,
) -> tuple[str, list[str]]:
    kept, blocked = select_modules(chosen, parse_denied(denied))
    searches = clean_search_names(instances)
    folder = script_folder_name(plugin_name)
    header = HEADER.replace("{{searches}}", " ".join(searches)).replace("{{plugin}}", folder)
    parts = [header.rstrip(), ""]
    for name in kept:
        body = MODULES.get(name, "").strip()
        if body:
            parts.append(body)
            parts.append("")
    if searches:
        parts.append(INSTANCE_SEARCH.strip())
        parts.append("")
    parts.append("# 고른 모듈만 실행. 하나가 깨져도 나머지는 계속 돈다.")
    for name in kept:
        parts.append(f"run_check check_{name}")
    if searches:
        parts.append("run_check check_instance_search")
    parts.append(FOOTER)
    script = "\n".join(parts).replace("\r\n", "\n")
    if not script.startswith("#!"):
        script = "#!/bin/bash\n" + script
    return script, blocked
