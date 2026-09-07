#!/bin/bash
# Guardian 이 SSH 로 붙어 이 내용을 그대로 실행하고, 마지막에 찍힌 JSON 한 덩어리를 받아 갑니다.
# {{server}} 와 {{instances}} 는 등록한 서버 이름과 인스턴스 목록으로 바뀝니다.
set -uo pipefail

SERVER_NAME="{{server}}"
INSTANCES="{{instances}}"
DATE="$(date +%F)"
HOUR="$(date +%H)"
STATE_DIR="${STATE_DIR:-/tmp/guardian-resource}"
mkdir -p "$STATE_DIR" 2>/dev/null || STATE_DIR="."
SAMPLE_FILE="$STATE_DIR/.samples-${SERVER_NAME}-${DATE}.tsv"

CORES=$(nproc 2>/dev/null || echo 1)

cpu_now() {
  if [ -r /proc/loadavg ]; then
    awk -v cores="$CORES" '{
      pct = $1 * 100 / cores
      if (pct < 0) pct = 0
      if (pct > 100) pct = 100
      printf "%.1f", pct
    }' /proc/loadavg
  else
    echo "0.0"
  fi
}

mem_now() {
  if command -v free >/dev/null 2>&1; then
    free -m | awk '/^Mem:/ {printf "%.1f", ($2 > 0) ? $3 * 100 / $2 : 0}'
  else
    echo "0.0"
  fi
}

# 이번 시각 표본을 남긴다. 같은 시각에 또 돌면 덮어쓴다.
if [ -f "$SAMPLE_FILE" ]; then
  awk -F'\t' -v hour="$HOUR" '$1 != hour' "$SAMPLE_FILE" > "${SAMPLE_FILE}.tmp" 2>/dev/null || true
  mv "${SAMPLE_FILE}.tmp" "$SAMPLE_FILE" 2>/dev/null || true
fi
printf '%s\t%s\t%s\n' "$HOUR" "$(cpu_now)" "$(mem_now)" >> "$SAMPLE_FILE"
sort -o "$SAMPLE_FILE" "$SAMPLE_FILE" 2>/dev/null || true

stat_of() {
  awk -F'\t' -v col="$1" -v mode="$2" '
    { sum += $col; if ($col > max) max = $col; n++ }
    END {
      if (n == 0) { printf "0.0"; exit }
      if (mode == "max") printf "%.1f", max; else printf "%.1f", sum / n
    }' "$SAMPLE_FILE"
}

samples_json() {
  awk -F'\t' '{
    if (n++) printf ", "
    printf "{\"hour\": \"%s\", \"cpu_pct\": %s, \"mem_pct\": %s}", $1, $2, $3
  }' "$SAMPLE_FILE"
}

mem_json() {
  swap=$(free -m 2>/dev/null | awk '/^Swap:/ {printf "%.1f", ($2 > 0) ? $3 * 100 / $2 : 0}')
  [ -z "$swap" ] && swap="0.0"
  if command -v free >/dev/null 2>&1; then
    free -m | awk -v swap="$swap" -v peak="$(stat_of 3 max)" '/^Mem:/ {
      used = $3; total = $2
      pct = (total > 0) ? used * 100 / total : 0
      printf "{\"used_pct\": %.1f, \"peak_pct\": %s, \"used_mb\": %s, \"total_mb\": %s, \"swap_used_pct\": %s}", pct, peak, used, total, swap
    }'
  else
    echo '{"used_pct": 0}'
  fi
}

disk_json() {
  df -P -k 2>/dev/null | awk 'NR > 1 && $6 ~ /^\// && $2 > 0 {
    gsub(/%/, "", $5)
    if (n++) printf ", "
    printf "{\"mount\": \"%s\", \"used_pct\": %s, \"used_gb\": %.1f, \"total_gb\": %.1f, \"free_gb\": %.1f}", \
      $6, $5, $3 / 1048576, $2 / 1048576, $4 / 1048576
  }'
}

instance_json() {
  first=1
  for name in $INSTANCES; do
    [ -z "$name" ] && continue
    ok=false
    detail="not found"
    restarts=0
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$name" 2>/dev/null; then
      ok=true
      detail="active"
      restarts=$(systemctl show -p NRestarts --value "$name" 2>/dev/null || echo 0)
      [ -z "$restarts" ] && restarts=0
    elif pgrep -f "$name" >/dev/null 2>&1; then
      ok=true
      detail="process"
    fi
    usage=$(ps -eo comm,pcpu,rss,args --no-headers 2>/dev/null | awk -v name="$name" '
      index($0, name) > 0 { cpu += $2; rss += $3; pids++ }
      END { printf "%.1f %.1f %d", cpu, rss / 1024, pids }')
    cpu_pct=$(echo "$usage" | awk '{print $1}')
    mem_mb=$(echo "$usage" | awk '{print $2}')
    pids=$(echo "$usage" | awk '{print $3}')
    [ $first -eq 1 ] || printf ", "
    first=0
    printf '{"name": "%s", "ok": %s, "detail": "%s", "cpu_pct": %s, "mem_mb": %s, "restarts": %s, "pids": %s}' \
      "$name" "$ok" "$detail" "${cpu_pct:-0}" "${mem_mb:-0}" "${restarts:-0}" "${pids:-0}"
  done
}

top_json() {
  ps -eo comm,pcpu,pmem --no-headers --sort=-pcpu 2>/dev/null | head -n 5 | awk '{
    if (n++) printf ", "
    printf "{\"name\": \"%s\", \"cpu_pct\": %s, \"mem_pct\": %s}", $1, $2, $3
  }'
}

cat <<EOF
{
  "server": "${SERVER_NAME}",
  "date": "${DATE}",
  "cpu": {
    "usage_pct": $(stat_of 2 avg),
    "peak_pct": $(stat_of 2 max),
    "cores": ${CORES},
    "samples": [$(samples_json)]
  },
  "mem": $(mem_json),
  "disk": [$(disk_json)],
  "instances": [$(instance_json)],
  "top": [$(top_json)]
}
EOF
