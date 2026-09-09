"""
도구 3개를 실제로 이어붙여서 파이프라인이 동작하는지 확인하는 스모크 테스트.
에이전트 루프를 아직 만들기 전 단계에서, "이 부품들이 서로 맞물리는가"를
사람이 눈으로 확인하기 위한 스크립트다 (pytest 아님, 그냥 실행 스크립트).

시나리오: 2025-04 ~ 2026-03(12개월)의 "오퍼 발송 대비 수락률"을 한 달씩 조회해
시계열을 만들고, run_chart_code로 2026-03(의도적으로 주입한 이상치 기간)이
실제로 관리도 상 이상치로 잡히는지 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.query_recruiting_db import query_recruiting_db
from app.tools.run_chart_code import run_chart_code
from app.tools.write_insight_draft import write_insight_draft
from app.insight_store import get_draft


def month_series(start_year, start_month, n):
    periods = []
    y, m = start_year, start_month
    for _ in range(n):
        periods.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return periods


def offer_conversion_rate(period: str) -> float:
    result = query_recruiting_db(period={"start": period, "end": period}, metric="funnel")
    counts = {row["stage"]: row["count"] for row in result["rows"]}
    sent, signed = counts.get("offer_sent", 0), counts.get("offer_signed", 0)
    return round(signed / sent, 4) if sent else 0.0


def main():
    periods = month_series(2025, 4, 12)  # 2025-04 ~ 2026-03
    series = [offer_conversion_rate(p) for p in periods]

    print("=== 1) query_recruiting_db: 월별 오퍼 수락률 시계열 ===")
    for p, v in zip(periods, series):
        print(f"  {p}: {v}")

    print("\n=== 2) run_chart_code: 관리도 기반 이상치 판단 (마지막 달 = 2026-03) ===")
    chart_result = run_chart_code(metric_series=series, sigma_multiplier=2.0)
    print(f"  {chart_result}")
    assert chart_result["is_outlier"], "기대한 이상치(2026-03 오퍼 수락률 급락)를 못 잡았습니다!"
    print("  OK: 의도적으로 주입한 이상치를 정상적으로 탐지했습니다.")

    print("\n=== 3) write_insight_draft: 우리 DB에 인사이트 초안 저장 (status=draft) ===")
    run_id = "smoke-test-run-1"
    write_result = write_insight_draft(
        run_id=run_id,
        period="2026-03",
        summary_text="2026-03 오퍼 수락률이 관리 하한(LCL) 아래로 급락했습니다.",
        root_cause_text=(
            f"평균 {chart_result['mean']} / LCL {chart_result['lcl']} 대비 "
            f"실제값 {chart_result['current_value']}로 통계적으로 유의한 이상치."
        ),
        next_action_text="해당 기간 오퍼 발송 후 후속 커뮤니케이션 프로세스를 점검할 것을 제안합니다.",
        generated_at="smoke-test",
    )
    print(f"  {write_result}")
    saved = get_draft(run_id)
    assert saved is not None and saved["status"] == "draft", "저장된 초안을 못 찾았거나 상태가 draft가 아닙니다!"
    print(f"  OK: DB에서 다시 읽어 확인 — status={saved['status']}")

    print("\n모든 스모크 테스트 통과.")


if __name__ == "__main__":
    main()
