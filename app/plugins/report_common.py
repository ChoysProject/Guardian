from __future__ import annotations

from collections import defaultdict
from html import escape


def render_standard_report(ctx, extra_sections: list[tuple[str, str]] | None = None) -> dict:
    """Stage 3 공통 골격. 서버별 플러그인은 title/intro만 바꾸고 이걸 호출하면 된다."""
    findings = list(ctx.findings or [])
    cfg = ctx.config or {}
    stats = cfg.get("stats") if isinstance(cfg.get("stats"), dict) else {}
    server_name = cfg.get("server_name") or ctx.server_name
    title = cfg.get("title") or "Goodmorning Check 로그 분석 보고서"
    if server_name and server_name not in ("*", "", "-") and "{server}" in title:
        title = title.replace("{server}", str(server_name))
    elif (
        server_name
        and server_name not in ("*", "", "-")
        and cfg.get("mode") == "per_server"
        and str(server_name) not in str(title)
    ):
        title = f"{title} · {server_name}"
    start = ctx.period_start.strftime("%Y-%m-%d") if ctx.period_start else ""
    end = ctx.period_end.strftime("%Y-%m-%d %H:%M") if ctx.period_end else ""

    by_severity: dict[str, int] = defaultdict(int)
    by_server: dict[str, int] = defaultdict(int)
    for item in findings:
        by_severity[item.get("severity", "info")] += 1
        by_server[item.get("server") or item.get("host") or "-"] += 1

    error_count = by_severity.get("error", 0)
    warn_count = by_severity.get("warn", 0)
    lines = int(stats.get("lines") or 0)
    error_lines = int(stats.get("error") or 0)
    warn_lines = int(stats.get("warn") or 0)
    summary_bits = [f"징후 {len(findings)}건 (error {error_count}, warn {warn_count})"]
    if lines:
        summary_bits.append(f"처리 로그 {lines:,}줄")
    if error_lines or warn_lines:
        summary_bits.append(f"ERROR 줄 {error_lines:,} · WARN 줄 {warn_lines:,}")
    summary = " · ".join(summary_bits)
    intro = (cfg.get("intro") or "").strip()

    md_lines = [f"# {title}", "", f"- 기간: {start} ~ {end}", f"- 요약: {summary}"]
    if server_name and server_name not in ("*", ""):
        md_lines.append(f"- 대상: {server_name}")
    if stats.get("last_collect"):
        md_lines.append(f"- 마지막 수집: {stats.get('last_collect')}")
    if int(stats.get("files") or 0):
        md_lines.append(f"- 따라가는 로그 파일: {int(stats.get('files'))}개")
    if lines:
        md_lines.append(
            f"- 오늘 처리: {lines:,}줄 (ERROR {error_lines:,} / WARN {warn_lines:,} / "
            f"INFO {int(stats.get('info') or 0):,} / DEBUG {int(stats.get('debug') or 0):,})"
        )
    if int(stats.get("older_findings") or 0):
        md_lines.append(f"- 이전 날짜 징후: {int(stats.get('older_findings'))}건")
    if intro:
        md_lines += ["", intro]
    md_lines += ["", "## 1. 심각도 집계", ""]
    if by_severity:
        for severity, count in sorted(by_severity.items()):
            md_lines.append(f"- {severity}: {count}")
    else:
        md_lines.append("- 해당 기간 Finding 없음")

    md_lines += ["", "## 2. 서버별 집계", ""]
    if by_server:
        for server, count in sorted(by_server.items()):
            md_lines.append(f"- {server}: {count}")
    else:
        md_lines.append("- 없음")

    for heading, body in extra_sections or []:
        md_lines += ["", f"## {heading}", "", body]

    md_lines += ["", "## 주요 이상징후", ""]
    ranked = sorted(findings, key=lambda item: (item.get("severity") != "error", -int(item.get("count") or 0)))
    if not ranked:
        if lines:
            md_lines.append(f"오늘 로그 {lines:,}줄을 처리했고, 규칙에 걸린 징후는 없습니다.")
        else:
            md_lines.append("오늘 이 서버에서 처리한 로그가 아직 없거나, 규칙에 걸린 징후가 없습니다.")
    for item in ranked[:30]:
        md_lines.append(
            f"- **[{item.get('severity')}]** `{item.get('signature')}` "
            f"x{item.get('count')} ({item.get('server') or item.get('host')}, {item.get('plugin')})"
        )
        comment = (item.get("ai_comment") or "").strip()
        if comment:
            md_lines.append(f"  - AI: {comment}")

    md_lines += ["", "## 샘플 로그", ""]
    for item in ranked[:10]:
        md_lines.append(f"### {item.get('signature')}")
        for line in (item.get("sample_lines") or [])[:3]:
            md_lines.append(f"    {line}")
        md_lines.append("")

    markdown = "\n".join(md_lines)
    html = _to_html(title, start, end, summary, by_severity, by_server, ranked, intro, stats)
    return {
        "title": f"{start} {title}".strip(),
        "summary": summary,
        "markdown": markdown,
        "html": html,
    }


def _severity_level(value: str) -> str:
    text = (value or "").lower()
    if text == "error":
        return "danger"
    if text == "warn":
        return "warn"
    return "ok"


def _to_html(title, start, end, summary, by_severity, by_server, ranked, intro="", stats=None) -> str:
    stats = stats if isinstance(stats, dict) else {}
    error_count = int(by_severity.get("error") or 0)
    warn_count = int(by_severity.get("warn") or 0)
    finding_count = len(ranked)
    lines = int(stats.get("lines") or 0)
    error_lines = int(stats.get("error") or 0)
    warn_lines = int(stats.get("warn") or 0)
    files = int(stats.get("files") or 0)
    older = int(stats.get("older_findings") or 0)
    last_collect = str(stats.get("last_collect") or "")
    if error_count:
        overall, verdict = "danger", f"ERROR 징후 {error_count}건이 있어 바로 확인이 필요합니다."
    elif error_lines:
        overall, verdict = "warn", f"ERROR 줄 {error_lines:,}건이 있으나 규칙에 걸린 징후는 없습니다. 1단계 플러그인을 확인해 보세요."
    elif warn_count:
        overall, verdict = "warn", f"WARN 징후 {warn_count}건이 있어 추이를 봐야 합니다."
    elif warn_lines:
        overall, verdict = "warn", f"WARN 줄 {warn_lines:,}건이 있으나 징후로 묶이지는 않았습니다."
    elif finding_count:
        overall, verdict = "ok", "징후는 있으나 ERROR·WARN은 없습니다."
    elif lines:
        overall, verdict = "ok", f"오늘 로그 {lines:,}줄을 처리했고, 규칙에 걸린 징후는 없습니다."
    else:
        overall, verdict = "ok", "오늘 이 서버에서 처리한 로그가 아직 없습니다."
        if older:
            verdict += f" 이전 날짜 징후 {older}건이 남아 있습니다."

    rows = []
    for item in ranked[:50]:
        severity = str(item.get("severity") or "")
        samples = "<br>".join(escape(str(line)) for line in (item.get("sample_lines") or [])[:3])
        comment = escape(item.get("ai_comment") or "") or "-"
        rows.append(
            "<tr>"
            f'<td><span class="tag {_severity_level(severity)}">{escape(severity)}</span></td>'
            f"<td>{escape(str(item.get('server') or item.get('host') or '-'))}</td>"
            f"<td><code>{escape(str(item.get('signature') or ''))}</code></td>"
            f"<td>{escape(str(item.get('count') or 0))}</td>"
            f"<td>{escape(str(item.get('plugin') or '-'))}</td>"
            f"<td>{comment}</td>"
            f"<td><pre>{samples or '-'}</pre></td>"
            "</tr>"
        )
    intro_html = f'<p class="intro">{escape(intro)}</p>' if intro else ""
    body = "\n".join(rows) or (
        "<tr><td colspan='7' class='empty'>"
        + escape(
            f"오늘 로그 {lines:,}줄을 봤고 징후는 없습니다."
            if lines
            else "Finding 없음"
        )
        + "</td></tr>"
    )
    collect_html = ""
    bits = []
    if last_collect:
        bits.append(f"마지막 수집 {escape(last_collect)}")
    if files:
        bits.append(f"로그 파일 {files}개")
    if older:
        bits.append(f"이전 날짜 징후 {older}건")
    if bits:
        collect_html = f'<div class="meta">{ " · ".join(bits) }</div>'
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --card: #fff;
      --line: #e6e8ee;
      --text: #1d2433;
      --muted: #667085;
      --ok: #067647;
      --ok-bg: #ecfdf3;
      --warn: #b54708;
      --warn-bg: #fffaeb;
      --danger: #b42318;
      --danger-bg: #fef3f2;
    }}
    body {{ font-family: "Segoe UI", "Apple SD Gothic Neo", sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
    .wrap {{ max-width: 960px; margin: 0 auto; padding: 32px 24px 48px; }}
    h1 {{ font-size: 1.45rem; margin: 0 0 6px; }}
    h2 {{ font-size: 0.95rem; margin: 28px 0 10px; color: #344054; }}
    .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 16px; }}
    .intro {{ color: var(--text); line-height: 1.55; }}
    .verdict {{ display: flex; align-items: center; gap: 10px; padding: 14px 16px; border-radius: 14px; background: var(--card); border: 1px solid var(--line); margin-bottom: 16px; font-weight: 650; }}
    .verdict.ok {{ background: var(--ok-bg); border-color: #abefc6; color: var(--ok); }}
    .verdict.warn {{ background: var(--warn-bg); border-color: #fedf89; color: var(--warn); }}
    .verdict.danger {{ background: var(--danger-bg); border-color: #fecdca; color: var(--danger); }}
    .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 8px; }}
    .kpi {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; }}
    .kpi.ok {{ border-color: #abefc6; }}
    .kpi.warn {{ border-color: #fedf89; background: var(--warn-bg); }}
    .kpi.danger {{ border-color: #fecdca; background: var(--danger-bg); }}
    .kpi .label {{ color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .kpi .value {{ font-size: 1.7rem; font-weight: 700; letter-spacing: -0.03em; }}
    .kpi .note {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--line); font-size: 13px; vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; background: #fafbff; }}
    tr:last-child td {{ border-bottom: 0; }}
    code, pre {{ font-family: Consolas, "Apple SD Gothic Neo", monospace; background: #f2f4f7; padding: 2px 6px; border-radius: 6px; white-space: pre-wrap; }}
    pre {{ margin: 0; padding: 8px; }}
    .tag {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; font-weight: 650; }}
    .tag.ok {{ background: var(--ok-bg); color: var(--ok); }}
    .tag.warn {{ background: var(--warn-bg); color: var(--warn); }}
    .tag.danger {{ background: var(--danger-bg); color: var(--danger); }}
    .empty {{ color: var(--muted); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{escape(title)}</h1>
    <div class="meta">기간 {escape(str(start))} ~ {escape(str(end))} · {escape(summary)}</div>
    {collect_html}
    {intro_html}
    <div class="verdict {overall}">{escape(verdict)}</div>
    <div class="kpis">
      <div class="kpi"><div class="label">처리 로그</div><div class="value">{lines:,}</div><div class="note">오늘 읽은 줄</div></div>
      <div class="kpi {'danger' if error_lines else 'ok'}"><div class="label">ERROR 줄</div><div class="value">{error_lines:,}</div></div>
      <div class="kpi {'warn' if warn_lines else 'ok'}"><div class="label">WARN 줄</div><div class="value">{warn_lines:,}</div></div>
      <div class="kpi {'danger' if error_count else ('warn' if warn_count else 'ok')}"><div class="label">징후</div><div class="value">{finding_count}</div><div class="note">규칙에 걸린 건</div></div>
    </div>
    <h2>징후 목록</h2>
    <table>
      <thead><tr><th>심각도</th><th>서버</th><th>시그니처</th><th>건수</th><th>플러그인</th><th>AI</th><th>샘플</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</body>
</html>
"""

