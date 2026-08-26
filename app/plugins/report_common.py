from __future__ import annotations

from collections import defaultdict
from html import escape


def render_standard_report(ctx, extra_sections: list[tuple[str, str]] | None = None) -> dict:
    """Stage 3 공통 골격. 서버별 플러그인은 title/intro만 바꾸고 이걸 호출하면 된다."""
    findings = list(ctx.findings or [])
    cfg = ctx.config or {}
    server_name = cfg.get("server_name") or ctx.server_name
    title = cfg.get("title") or "Goodmorning Check 로그 분석 보고서"
    if server_name and server_name not in ("*", "", "-") and "{server}" in title:
        title = title.replace("{server}", str(server_name))
    elif server_name and server_name not in ("*", "", "-") and cfg.get("mode") == "per_server":
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
    summary = f"징후 {len(findings)}건 (error {error_count}, warn {warn_count})"
    intro = (cfg.get("intro") or "").strip()

    md_lines = [f"# {title}", "", f"- 기간: {start} ~ {end}", f"- 요약: {summary}"]
    if server_name and server_name not in ("*", ""):
        md_lines.append(f"- 대상: {server_name}")
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
        md_lines.append("이상징후가 없습니다.")
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
    html = _to_html(title, start, end, summary, by_severity, by_server, ranked, intro)
    return {
        "title": f"{start} {title}".strip(),
        "summary": summary,
        "markdown": markdown,
        "html": html,
    }


def _to_html(title, start, end, summary, by_severity, by_server, ranked, intro="") -> str:
    rows = []
    for item in ranked[:50]:
        samples = "<br>".join(escape(str(line)) for line in (item.get("sample_lines") or [])[:3])
        comment = escape(item.get("ai_comment") or "")
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('severity')))}</td>"
            f"<td>{escape(str(item.get('server') or item.get('host')))}</td>"
            f"<td><code>{escape(str(item.get('signature')))}</code></td>"
            f"<td>{item.get('count')}</td>"
            f"<td>{escape(str(item.get('plugin')))}</td>"
            f"<td>{comment}</td>"
            f"<td><pre>{samples}</pre></td>"
            "</tr>"
        )
    sev = "".join(f"<li>{escape(k)}: {v}</li>" for k, v in sorted(by_severity.items()))
    srv = "".join(f"<li>{escape(k)}: {v}</li>" for k, v in sorted(by_server.items()))
    intro_html = f"<p>{escape(intro)}</p>" if intro else ""
    body = "\n".join(rows) or "<tr><td colspan='7'>Finding 없음</td></tr>"
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{escape(title)}</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; background: #12141a; color: #e8e4d9; margin: 32px; }}
    h1,h2 {{ font-weight: 600; }}
    code, pre {{ font-family: Consolas, monospace; background: #1b1f28; padding: 2px 6px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border-bottom: 1px solid #2a3140; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ color: #d4a017; }}
  </style>
</head>
<body>
  <h1>{escape(title)}</h1>
  <p>기간: {escape(str(start))} ~ {escape(str(end))}<br>요약: {escape(summary)}</p>
  {intro_html}
  <h2>심각도</h2><ul>{sev or "<li>없음</li>"}</ul>
  <h2>서버</h2><ul>{srv or "<li>없음</li>"}</ul>
  <h2>징후 목록</h2>
  <table>
    <thead><tr><th>심각도</th><th>서버</th><th>시그니처</th><th>건수</th><th>플러그인</th><th>AI</th><th>샘플</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</body>
</html>
"""
