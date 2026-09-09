"""
핵심지표 화면용 피벗 헬퍼.

기간이 세로로 24줄 나열된 표는 추세를 한눈에 보기 어렵다는 사용자 피드백(2026-09-09)으로,
기간을 가로축(컬럼)으로 돌리고 값 크기에 따라 배경색 진하기(heatmap)를 넣어 한 줄만 훑어도
그 항목이 어떻게 변해왔는지 바로 보이게 만든다.
"""


def _cells(values: list) -> list:
    numeric = [v for v in values if v is not None]
    vmin, vmax = (min(numeric), max(numeric)) if numeric else (0, 0)
    cells = []
    for v in values:
        if v is None:
            cells.append({"value": None, "intensity": 0})
        else:
            intensity = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.5
            cells.append({"value": v, "intensity": round(intensity, 2)})
    return cells


def pivot_long(rows: list, item_key: str = "item", period_key: str = "period",
               value_key: str = "value") -> tuple:
    """[{period, item, value}, ...] -> (정렬된 기간 목록, [{item, cells:[{value,intensity}]}, ...])"""
    periods = sorted({r[period_key] for r in rows})
    items = sorted({r[item_key] for r in rows})
    grid = {item: {} for item in items}
    for r in rows:
        grid[r[item_key]][r[period_key]] = r[value_key]
    table = [{"item": item, "cells": _cells([grid[item].get(p) for p in periods])} for item in items]
    return periods, table


def pivot_kpi(kpi_rows: list) -> tuple:
    """build_kpi_rows() 결과(월별 1행, 지표 4개 컬럼)를 지표별 1행으로 돌린다."""
    metric_labels = {
        "total_applicant": "총지원자", "self_drop": "자진포기",
        "rejected": "불합격", "in_progress": "진행중",
    }
    periods = [r["period"] for r in kpi_rows]  # 이미 시간순
    table = [
        {"item": label, "cells": _cells([r[key] for r in kpi_rows])}
        for key, label in metric_labels.items()
    ]
    return periods, table
