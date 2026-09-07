#!/bin/bash
# 각 서버에 두고 cron 으로 매시간 한 번 실행하세요.
# 실행할 때마다 그 시각 표본을 쌓고, 오늘 자 JSON 파일을 다시 만듭니다.
# 그 JSON 을 Guardian > 서버 > 서버 리소스 분석 화면에 넣으면
# 보고서 > 리소스 분석 보고서 에서 일주일 추이와 AI 총평이 나옵니다.
#
# 예) 0 * * * * SERVER_NAME=eai-01 INSTANCES="was mq" /opt/guardian/sample_resource.sh
set -euo pipefail

SERVER_NAME="${SERVER_NAME:-$(hostname -s)}"
DATE="${DATE:-$(date +%F)}"
HOUR="${HOUR:-$(date +%H)}"
OUT_DIR="${OUT_DIR:-/var/log/guardian-resource}"
INSTANCES="${INSTANCES:-was mq}"
KEEP_DAYS="${KEEP_DAYS:-14}"

mkdir -p "$OUT_DIR"
OUT_FILE="$OUT_DIR/${SERVER_NAME}-${DATE}.json"
SAMPLE_FILE="$OUT_DIR/.samples-${SERVER_NAME}-${DATE}.tsv"

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

load1() {
  if [ -r /proc/loadavg ]; then awk '{printf "%.2f", $1}' /proc/loadavg; else echo "0"; fi
}

# 1) 이번 시각 표본을 한 줄 남긴다. 같은 시각을 다시 돌리면 덮어쓴다.
if [ -f "$SAMPLE_FILE" ]; then
  awk -F'\t' -v hour="$HOUR" '$1 != hour' "$SAMPLE_FILE" > "${SAMPLE_FILE}.tmp" || true
  mv "${SAMPLE_FILE}.tmp" "$SAMPLE_FILE"
fi
printf '%s\t%s\t%s\n' "$HOUR" "$(cpu_now)" "$(mem_now)" >> "$SAMPLE_FILE"
sort -o "$SAMPLE_FILE" "$SAMPLE_FILE"

stat_of() {
  # $1: 열 번호(2=cpu, 3=mem), $2: avg|max
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
  local swap
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
  df -P -k -x tmpfs -x devtmpfs 2>/dev/null | awk 'NR > 1 && $6 ~ /^\// {
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
    # 이름으로 잡히는 프로세스의 CPU / 메모리 합계
    usage=$(ps -eo comm,pcpu,rss,args --no-headers 2>/dev/null | awk -v name="$name" '
      index($0, name) > 0 && index($0, "sample_resource") == 0 {
        cpu += $2; rss += $3; pids++
      }
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

cat > "$OUT_FILE" <<EOF
{
  "server": "${SERVER_NAME}",
  "date": "${DATE}",
  "cpu": {
    "usage_pct": $(stat_of 2 avg),
    "peak_pct": $(stat_of 2 max),
    "cores": ${CORES},
    "load1": $(load1),
    "samples": [$(samples_json)]
  },
  "mem": $(mem_json),
  "disk": [$(disk_json)],
  "instances": [$(instance_json)],
  "top": [$(top_json)]
}
EOF

# 오래된 표본 파일 정리
find "$OUT_DIR" -name ".samples-*" -type f -mtime "+${KEEP_DAYS}" -delete 2>/dev/null || true

echo "$OUT_FILE"
