from app.pipeline.stage1 import analyze_common


def analyze(ctx) -> list[dict]:
    """모든 서버에 공통으로 도는 1단계. 서버 고유 문구는 여기 넣지 않는다."""
    return analyze_common(ctx.events, host=ctx.host, config=ctx.config or {})
