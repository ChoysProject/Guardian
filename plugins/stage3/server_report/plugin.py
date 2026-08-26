from app.plugins.report_common import render_standard_report


def render(ctx) -> dict:
    """서버 하나분의 Finding만 받는다. mode: per_server 가 서버별로 이 함수를 호출한다."""
    result = render_standard_report(ctx)
    server = (ctx.config or {}).get("server_name") or ctx.server_name or "server"
    result["plugin"] = f"server_report:{server}"
    return result
