from app.plugins.report_common import render_standard_report


def render(ctx) -> dict:
    result = render_standard_report(ctx)
    result["plugin"] = "daily_report"
    return result
