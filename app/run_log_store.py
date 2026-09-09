"""
에이전트 실행(run) 상태 저장소 — PRD 4.4(상태관리·재개), 7장(관찰가능성).

runs 테이블에 실행 하나의 진행 상태를, run_events 테이블에 그 안의 도구 호출
trace를 남긴다. 나중에 만들 "실행 로그" 화면이 run_events를 그대로 읽어서
"왜 호출했는지 → 뭘 호출했는지 → 뭘 받았는지"를 보여주면 된다.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import APP_DB_PATH


def _connect():
    conn = sqlite3.connect(APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    schema_sql = (Path(__file__).parent / "app_db_schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def start_run(run_id: str, period: str, filters: dict | None) -> None:
    # OR IGNORE: 웹앱은 백그라운드 스레드를 시작하기 *전에* 이 함수를 먼저 호출해서
    # run_id가 즉시 조회 가능하게 만든다(그래야 리다이렉트 직후 GET이 404 안 남).
    # run_agent()도 독립 실행(CLI/테스트)을 위해 이 함수를 다시 호출하므로, 두 번째
    # 호출은 조용히 무시되어야 한다.
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO runs (run_id, period, filters_json, status, started_at) "
            "VALUES (?, ?, ?, 'running', ?)",
            (run_id, period, json.dumps(filters or {}, ensure_ascii=False), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def log_event(run_id: str, step_no: int, event_type: str, tool_name: str | None = None,
              tool_input: dict | None = None, tool_output: dict | None = None,
              reasoning_text: str | None = None, latency_ms: int | None = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO run_events (run_id, step_no, event_type, tool_name, tool_input_json, "
            "tool_output_json, reasoning_text, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, step_no, event_type, tool_name,
             json.dumps(tool_input, ensure_ascii=False) if tool_input is not None else None,
             json.dumps(tool_output, ensure_ascii=False) if tool_output is not None else None,
             reasoning_text, latency_ms, _now()),
        )
        if event_type == "tool_call" and tool_name == "query_recruiting_db":
            conn.execute("UPDATE runs SET query_round_count = query_round_count + 1 WHERE run_id = ?",
                         (run_id,))
        conn.commit()
    finally:
        conn.close()


def add_token_usage(run_id: str, input_tokens: int, output_tokens: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE runs SET total_input_tokens = total_input_tokens + ?, "
            "total_output_tokens = total_output_tokens + ? WHERE run_id = ?",
            (input_tokens, output_tokens, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def finish_run(run_id: str, status: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
            (status, _now(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_runs(limit: int = 50) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_events(run_id: str) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY step_no", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
