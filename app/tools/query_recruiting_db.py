"""
도구 1: query_recruiting_db (PRD.md 5장)

채용 집계 데이터를 조회하는 읽기 전용 도구. 화이트리스트된 쿼리 템플릿만
허용하고, 임의 SQL 실행은 절대 받지 않는다(DB 인젝션·스코프 이탈 방지).

에이전트에게 줄 description:
    "기간 내 채용 지표가 필요할 때마다 호출한다. metric으로 어떤 지표
    (퍼널/상태/진행중비율/채널/부서/소요기간/YTD)인지 지정하고, 절대 숫자를
    추측하지 않는다. 결과가 비어 있으면 해당 기간에 데이터가 없다는 뜻이다.
    period.start와 period.end에 여러 달을 걸치는 범위를 주면, 그 달들을
    합산한 값이 아니라 달마다 한 행씩(period 컬럼 포함) 나뉘어 돌아온다 —
    관리도용 시계열이 필요하면 이 범위 조회 한 번으로 만들 수 있다."

실패 사례(2026-09-09): 이 설명·period 분리 없이 배포했더니, 에이전트가 여러 달치
숫자가 하나로 합산된 걸 모르고 1개월 값과 3개월 합계값을 직접 비교하다가
run_chart_code(표본 3개 이상 필요)에서 계속 거부당했다. 재조회 한도(5회)를
전부 그렇게 낭비하고, 정작 방금 조회에서 이미 봤던 명백한 이상치
(offer_sent=15, offer_signed=0)를 인용하지 못한 채 "특이사항 없음"으로 결론
내렸다. 원인은 프롬프트가 아니라 이 도구가 기간을 조용히 합산해버린 것이었다.
"""
import re
import sqlite3
from typing import Literal, Optional, TypedDict

from app.config import DB_PATH

_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

Metric = Literal[
    "funnel", "status_counts", "in_progress_ratio",
    "channel", "department", "stage_duration", "ytd_summary",
]
Scope = Literal["all_applicants", "hired_only"]


class QueryInput(TypedDict, total=False):
    period: dict          # {"start": "YYYY-MM", "end": "YYYY-MM"}
    filters: dict          # {"department": str, "job_posting_id": str, "channel": str}
    metric: Metric
    scope: Optional[Scope]  # metric="channel"일 때만 사용


class QueryError(Exception):
    pass


_ALLOWED_METRICS = {
    "funnel": ("funnel_events", "stage, SUM(count) as count", "stage"),
    "status_counts": ("applicant_status_counts", "status, SUM(count) as count", "status"),
    "in_progress_ratio": ("in_progress_stage_ratio", "stage, AVG(ratio) as ratio", "stage"),
    "department": ("department_stats", "department, SUM(applicant_count) as applicant_count", "department"),
}


def query_recruiting_db(period: dict, metric: Metric,
                         filters: Optional[dict] = None,
                         scope: Optional[Scope] = None) -> dict:
    """읽기 전용 채용 집계 데이터 조회. 화이트리스트된 쿼리 템플릿만 실행한다."""
    filters = filters or {}
    start, end = period.get("start"), period.get("end")
    if not start or not end:
        raise QueryError("period.start / period.end는 필수입니다 (YYYY-MM 형식, 예: 2026-03).")
    if not (_PERIOD_RE.match(start) and _PERIOD_RE.match(end)):
        # 형식이 틀리면(예: YYYY-MM-DD) 문자열 비교로 조용히 빈 결과가 나올 수 있어
        # (예: "2025-11-01"~"2025-11-30" 범위에 "2025-11"이 문자열상 걸리지 않음),
        # "데이터 없음"과 헷갈리지 않도록 명확한 에러로 막는다.
        raise QueryError(
            f"period.start/end는 정확히 YYYY-MM 형식이어야 합니다 (받은 값: start={start!r}, end={end!r}). "
            "일(day)은 넣지 마세요 — 예: '2026-03', '2026-03-01' 아님."
        )

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if metric == "channel":
            rows = _query_channel(conn, start, end, filters, scope)
        elif metric == "stage_duration":
            rows = _query_stage_duration(conn, start, end, filters)
        elif metric == "ytd_summary":
            rows = _query_ytd(conn, filters)
        elif metric in _ALLOWED_METRICS:
            rows = _query_generic(conn, metric, start, end, filters)
        else:
            raise QueryError(f"허용되지 않는 metric입니다: {metric}")
    finally:
        conn.close()

    return {"rows": rows, "row_count": len(rows)}


def _query_generic(conn, metric, start, end, filters):
    # period도 항상 GROUP BY에 넣는다 — 여러 달을 조회하면 달마다 한 행씩 돌아오게
    # 해서, 기간을 합산해버리는(그래서 시계열을 만들 수 없게 되는) 실수를 막는다.
    table, select_cols, group_col = _ALLOWED_METRICS[metric]
    sql = f"SELECT period, {select_cols} FROM {table} WHERE period BETWEEN ? AND ?"
    params = [start, end]
    if filters.get("job_posting_id"):
        sql += " AND job_posting_id = ?"
        params.append(filters["job_posting_id"])
    if filters.get("department") and table == "department_stats":
        sql += " AND department = ?"
        params.append(filters["department"])
    sql += f" GROUP BY period, {group_col} ORDER BY period"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _query_channel(conn, start, end, filters, scope):
    scope = scope or "all_applicants"
    sql = ("SELECT period, channel, SUM(count) as count FROM channel_stats "
           "WHERE period BETWEEN ? AND ? AND scope = ?")
    params = [start, end, scope]
    if filters.get("job_posting_id"):
        sql += " AND job_posting_id = ?"
        params.append(filters["job_posting_id"])
    if filters.get("channel"):
        sql += " AND channel = ?"
        params.append(filters["channel"])
    sql += " GROUP BY period, channel ORDER BY period"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _query_stage_duration(conn, start, end, filters):
    sql = ("SELECT period, metric, department, AVG(avg_days) as avg_days FROM stage_duration "
           "WHERE period BETWEEN ? AND ?")
    params = [start, end]
    if filters.get("department"):
        sql += " AND department = ?"
        params.append(filters["department"])
    sql += " GROUP BY period, metric, department ORDER BY period"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _query_ytd(conn, filters):
    scope = filters.get("department") or "all"
    sql = "SELECT * FROM ytd_summary WHERE department_scope = ? ORDER BY year"
    return [dict(r) for r in conn.execute(sql, [scope]).fetchall()]
