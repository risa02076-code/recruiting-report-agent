"""
Google Sheets 쓰기 — kpi/detail/ytd 3개 탭 전용.

이 셋은 전부 판단 없는 고정 집계 결과라서, app/generate_report_tabs.py(LLM을
쓰지 않는 평범한 스크립트)가 직접 쓴다. 판단이 들어간 인사이트는 여기 오지
않는다 — app/insight_store.py를 통해 우리 앱 자체 DB(insight_drafts 테이블)에
저장되고, 승인 전/후 구분도 그 DB 안에서 상태값(draft/approved)으로 처리한다.
그래서 이 시트는 "승인 게이트"가 필요 없는 단일 스프레드시트다 — 매번 통째로
새로 써서 항상 최신 상태를 유지하면 된다(staging/published 분리 불필요).

GOOGLE_SERVICE_ACCOUNT_JSON / REPORT_SHEET_ID 환경변수가 없으면 로컬 JSON
폴백(data/sheet_local/)으로 동작한다.
"""
import json
from datetime import datetime, timezone

from app.config import GOOGLE_SERVICE_ACCOUNT_JSON, REPORT_SHEET_ID, LOCAL_SHEET_FALLBACK_DIR

TAB_LABELS_KO = {
    "kpi": "핵심지표",
    "detail": "세부지표",
    "ytd": "연간누적지표",
}

COLUMN_LABELS_KO = {
    "period": "기간", "year": "연도",
    "total_applicant": "총지원자", "self_drop": "자진포기",
    "rejected": "불합격", "in_progress": "진행중",
    "category": "구분", "item": "항목", "value": "값",
    "department_scope": "부서범위",
    "scope": "모집단구분",
    "joined_count": "입사인원", "hired_count": "채용인원",
    "avg_date_to_join": "평균입사소요일", "avg_date_to_hire": "평균채용소요일",
}

# detail 탭의 category/scope 값도 사람이 보는 셀 내용이라 한국어로 번역해서 쓴다.
DETAIL_CATEGORY_LABELS_KO = {
    "funnel": "퍼널", "department": "부서", "channel": "채널", "in_progress": "진행중비율",
}
DETAIL_SCOPE_LABELS_KO = {
    "all_applicants": "전체지원자", "hired_only": "합격자만", "": "",
}


class SheetWriteError(Exception):
    pass


def localize_detail_row(row: dict) -> dict:
    localized = dict(row)
    if "category" in localized:
        localized["category"] = DETAIL_CATEGORY_LABELS_KO.get(localized["category"], localized["category"])
    if "scope" in localized:
        localized["scope"] = DETAIL_SCOPE_LABELS_KO.get(localized["scope"], localized["scope"])
    return localized


def write_tab(tab: str, rows: list) -> dict:
    if tab not in TAB_LABELS_KO:
        raise SheetWriteError(f"허용되지 않는 tab입니다: {tab} (허용: {sorted(TAB_LABELS_KO)})")
    if not rows:
        raise SheetWriteError("rows가 비어 있습니다 — 빈 쓰기는 하지 않습니다.")
    if tab == "detail":
        rows = [localize_detail_row(r) for r in rows]

    if GOOGLE_SERVICE_ACCOUNT_JSON and REPORT_SHEET_ID:
        return _write_google_sheet(tab, rows)
    return _write_local_fallback(tab, rows)


def _write_google_sheet(tab: str, rows: list) -> dict:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        raise SheetWriteError(
            "gspread/google-auth가 설치되지 않았습니다. requirements.txt를 설치하세요."
        ) from e

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(GOOGLE_SERVICE_ACCOUNT_JSON, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(REPORT_SHEET_ID)
    sheet_tab_name = TAB_LABELS_KO[tab]
    worksheet = sheet.worksheet(sheet_tab_name)

    columns = list(rows[0].keys())
    header_ko = [COLUMN_LABELS_KO.get(col, col) for col in columns]
    values = [header_ko] + [[r.get(col, "") for col in columns] for r in rows]
    worksheet.clear()
    worksheet.update(values)

    return {"updated_range": f"{sheet_tab_name}!A1:{_col_letter(len(columns))}{len(values)}",
            "row_count": len(rows)}


def _write_local_fallback(tab: str, rows: list) -> dict:
    LOCAL_SHEET_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_SHEET_FALLBACK_DIR / f"{tab}.json"
    payload = {
        "tab": tab,
        "sheet_tab_name_ko": TAB_LABELS_KO[tab],
        "written_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated_range": f"local:{path}", "row_count": len(rows)}


def _col_letter(n: int) -> str:
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters
