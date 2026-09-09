"""
인사이트 저장소 (app_state.db의 insight_drafts 테이블).

두 종류의 호출자를 구분한다:
  - save_draft(): 에이전트 도구(app/tools/write_insight_draft.py)가 호출한다.
    항상 status='draft'로만 저장한다 — 에이전트는 승인 상태를 스스로 바꿀 수 없다.
  - approve(): 사람이 앱 UI에서 승인 버튼을 눌렀을 때만 서버가 호출한다.
    에이전트 도구 목록에는 이 함수가 노출되지 않는다 — 승인 권한 자체가
    에이전트에게 물리적으로 없다(PRD 6장, 5장 권한 최소화 원칙).
"""
import sqlite3
from pathlib import Path

from app.config import APP_DB_PATH


def _connect():
    conn = sqlite3.connect(APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    schema_sql = (Path(__file__).parent / "app_db_schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    return conn


def save_draft(run_id: str, period: str, summary_text: str, root_cause_text: str,
               next_action_text: str, generated_at: str) -> dict:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO insight_drafts "
            "(run_id, period, summary_text, root_cause_text, next_action_text, generated_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'draft')",
            (run_id, period, summary_text, root_cause_text, next_action_text, generated_at),
        )
        conn.commit()
    finally:
        conn.close()
    return {"run_id": run_id, "status": "draft"}


def get_draft(run_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM insight_drafts WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def approve(run_id: str) -> dict:
    """사람이 앱에서 승인 버튼을 눌렀을 때만 서버가 호출하는 함수 — 에이전트 도구 아님."""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE insight_drafts SET status = 'approved', approved_at = datetime('now') "
            "WHERE run_id = ?",
            (run_id,),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError(f"run_id를 찾을 수 없습니다: {run_id}")
    finally:
        conn.close()
    return {"run_id": run_id, "status": "approved"}
