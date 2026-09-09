"""
정기 리포트 탭 채우기 — LLM을 전혀 쓰지 않는 평범한 스크립트.

핵심지표/세부지표/연간누적지표는 전부 고정된 집계 쿼리라 판단이 필요 없다.
그래서 에이전트가 아니라 이 스크립트가 직접 DB를 조회해서 Google Sheets
staging의 kpi/detail/ytd 탭을 채운다. 매월 1일 스케줄(cron)로 돌리거나
수동 실행하면 된다.

인사이트(원인 분석·다음 조치 제안)는 이 스크립트의 역할이 아니다 —
그건 에이전트 루프(app/agent_loop.py, 아직 미구현)가 담당한다.

실행:
    python -m app.generate_report_tabs
"""
from app.generate_synthetic_data import PERIODS
from app.sheets_writer import write_tab
from app.tools.query_recruiting_db import query_recruiting_db

# ytd_summary에 실제로 들어있는 department_scope 값들 (app/generate_synthetic_data.py 참고).
# 부서가 늘어나면 여기도 같이 늘려야 한다 — DB에서 동적으로 목록을 뽑을 수도 있지만,
# MVP 단계에서는 고정값으로 충분하다.
YTD_DEPARTMENT_SCOPES = ["all", "Engineering"]


def build_kpi_rows() -> list:
    rows = []
    for period in PERIODS:
        result = query_recruiting_db(period={"start": period, "end": period}, metric="status_counts")
        counts = {r["status"]: r["count"] for r in result["rows"]}
        rows.append({
            "period": period,
            "total_applicant": counts.get("total_applicant", 0),
            "self_drop": counts.get("self_drop", 0),
            "rejected": counts.get("rejected", 0),
            "in_progress": counts.get("in_progress", 0),
        })
    return rows


def build_detail_rows() -> list:
    rows = []
    for period in PERIODS:
        p = {"start": period, "end": period}

        funnel = query_recruiting_db(period=p, metric="funnel")
        for r in funnel["rows"]:
            rows.append({"period": period, "category": "funnel", "item": r["stage"],
                         "scope": "", "value": r["count"]})

        department = query_recruiting_db(period=p, metric="department")
        for r in department["rows"]:
            rows.append({"period": period, "category": "department", "item": r["department"],
                         "scope": "", "value": r["applicant_count"]})

        for scope in ["all_applicants", "hired_only"]:
            channel = query_recruiting_db(period=p, metric="channel", scope=scope)
            for r in channel["rows"]:
                rows.append({"period": period, "category": "channel", "item": r["channel"],
                             "scope": scope, "value": r["count"]})

        in_progress = query_recruiting_db(period=p, metric="in_progress_ratio")
        for r in in_progress["rows"]:
            rows.append({"period": period, "category": "in_progress", "item": r["stage"],
                         "scope": "", "value": r["ratio"]})
    return rows


def build_ytd_rows() -> list:
    rows = []
    for scope in YTD_DEPARTMENT_SCOPES:
        result = query_recruiting_db(period={"start": PERIODS[0], "end": PERIODS[-1]},
                                      metric="ytd_summary", filters={"department": scope})
        rows.extend(result["rows"])
    return rows


def main():
    kpi_rows = build_kpi_rows()
    detail_rows = build_detail_rows()
    ytd_rows = build_ytd_rows()

    kpi_result = write_tab("kpi", kpi_rows)
    detail_result = write_tab("detail", detail_rows)
    ytd_result = write_tab("ytd", ytd_rows)

    print(f"kpi: {kpi_result}")
    print(f"detail: {detail_result}")
    print(f"ytd: {ytd_result}")


if __name__ == "__main__":
    main()
