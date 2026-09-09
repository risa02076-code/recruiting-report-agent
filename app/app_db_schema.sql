-- 우리 앱 자체의 운영 데이터 (recruiting.db와 분리 — 그쪽은 "원본 채용 데이터"이고
-- 합성 데이터를 재생성할 때마다 통째로 지워진다. 이쪽은 에이전트 실행 결과처럼
-- 재생성과 무관하게 남아있어야 하는 데이터를 담는다).

-- 에이전트의 판단 결과물(인사이트)을 담는다. Google Sheets가 아니라 여기 저장하고,
-- 사람 승인 전(draft)/후(approved)를 이 상태값으로 구분한다 — PRD 6장 human-in-the-loop.
CREATE TABLE IF NOT EXISTS insight_drafts (
    run_id            TEXT PRIMARY KEY,
    period            TEXT NOT NULL,
    summary_text      TEXT NOT NULL,
    root_cause_text   TEXT NOT NULL,
    next_action_text  TEXT NOT NULL,
    generated_at      TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
    approved_at       TEXT
);

-- 에이전트 루프 실행 상태 (PRD 4.4 상태관리, 7장 관찰가능성). 중간에 끊겨도 이어서
-- 진행할 수 있도록 run 단위로 상태를 남긴다.
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    period       TEXT NOT NULL,
    filters_json TEXT,
    status       TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'timeout')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    query_round_count INTEGER NOT NULL DEFAULT 0,
    total_input_tokens  INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0
);

-- run 안의 개별 도구 호출 trace (실행 로그 화면이 그대로 읽어서 보여줄 데이터).
CREATE TABLE IF NOT EXISTS run_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL REFERENCES runs(run_id),
    step_no       INTEGER NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('tool_call', 'agent_text', 'error')),
    tool_name     TEXT,
    tool_input_json  TEXT,
    tool_output_json TEXT,
    reasoning_text   TEXT,
    latency_ms    INTEGER,
    created_at    TEXT NOT NULL
);
