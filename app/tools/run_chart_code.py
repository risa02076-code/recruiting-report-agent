"""
도구 2: run_chart_code (PRD.md 4.2.1, 5장)

관리도(Control Chart) 통계값을 계산하는 코드 실행 도구.
시각화 자체는 Looker Studio가 담당하므로, 여기서는 이상치 판단에 필요한
평균/표준편차/관리상한/관리하한(UCL/LCL)만 순수 계산한다.

에이전트에게 줄 description:
    "과거 기간들의 지표 값 목록(metric_series)을 넣으면, 이번 기간이
    통계적으로 유의한 이상치인지 판단할 수 있는 UCL/LCL을 계산해준다.
    단순 전월 대비 증감률만으로 '이상치'라고 판단하지 말고, 반드시 이 도구로
    검증한 뒤에만 이상치라고 말한다."
"""
import statistics
from typing import TypedDict


class ChartCodeError(Exception):
    pass


class ControlChartInput(TypedDict, total=False):
    metric_series: list  # 과거 N개 기간의 지표 값 (마지막 값이 "이번 기간")
    sigma_multiplier: float  # 기본 2 (PRD DEFAULT_SIGMA_MULTIPLIER)


def run_chart_code(metric_series: list, sigma_multiplier: float = 2.0) -> dict:
    """관리도 기반 이상치 판단. metric_series의 마지막 값을 '이번 기간'으로 보고,
    그 이전 값들을 baseline으로 삼아 평균/표준편차/UCL/LCL을 계산한다."""
    if len(metric_series) < 3:
        raise ChartCodeError(
            "표본이 너무 적습니다(최소 3개 기간 필요) — 이상치 판단 없이 원값만 보고하세요.")

    *baseline, current = metric_series
    mean = statistics.mean(baseline)
    stddev = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0

    ucl = mean + sigma_multiplier * stddev
    lcl = mean - sigma_multiplier * stddev
    is_outlier = current > ucl or current < lcl

    return {
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "ucl": round(ucl, 4),
        "lcl": round(lcl, 4),
        "current_value": current,
        "is_outlier": is_outlier,
        "direction": "above_ucl" if current > ucl else ("below_lcl" if current < lcl else "within_range"),
    }
