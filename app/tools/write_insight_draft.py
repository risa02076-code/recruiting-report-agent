"""
도구 3: write_insight_draft (PRD.md 3.2, 5장)

에이전트에게 노출되는 유일한 쓰기 도구. 우리 앱 DB의 insight_drafts 테이블에
**항상 draft 상태로만** 기록한다 — 승인(approved로 바꾸는 것)은 이 도구가
할 수 없다. 사람이 앱 UI에서 승인 버튼을 눌렀을 때만 서버가 별도로 처리한다
(app/insight_store.py의 approve(), 에이전트 도구 목록에 없음).

핵심지표/세부지표/연간누적지표(Google Sheets)는 고정된 집계라 이 도구가
아니라 app/generate_report_tabs.py가 직접 쓴다 — 판단이 필요 없는 숫자는
에이전트 도구로 노출하지 않는다(5장 "위험한 도구 권한 최소화").

에이전트에게 줄 description:
    "이상치 판단과 원인 조사가 끝난 뒤, 그 결론(요약/원인분석/다음조치제안)을
    딱 한 번 기록할 때 호출한다. 항상 draft 상태로만 저장되며, 이 도구를
    호출한다고 해서 리크루터에게 바로 노출되지 않는다 — 사람이 앱에서 승인해야
    확정된다. 숫자 집계 데이터는 이미 다른 곳에 채워져 있으니 여기 넣지 않는다."
"""
from typing import TypedDict

from app.insight_store import save_draft


class WriteInsightDraftInput(TypedDict):
    run_id: str
    period: str
    summary_text: str
    root_cause_text: str
    next_action_text: str
    generated_at: str


def write_insight_draft(run_id: str, period: str, summary_text: str,
                         root_cause_text: str, next_action_text: str,
                         generated_at: str) -> dict:
    return save_draft(run_id, period, summary_text, root_cause_text, next_action_text, generated_at)
