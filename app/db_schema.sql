-- Recruiting Report Agent — SQLite schema
-- Mirrors PRD.md section 3 (집계값만, PII 없음)

CREATE TABLE IF NOT EXISTS job_postings (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    department      TEXT NOT NULL CHECK (department IN ('Engineering','Business','IT/DATA','Management Control','P&C')),
    channel_default TEXT NOT NULL,
    opened_date     TEXT NOT NULL,  -- YYYY-MM-DD
    closed_date     TEXT            -- YYYY-MM-DD, nullable (아직 진행중)
);

CREATE TABLE IF NOT EXISTS funnel_events (
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
    period         TEXT NOT NULL,  -- YYYY-MM
    stage          TEXT NOT NULL CHECK (stage IN (
        'application_stage','sc_stage','interview_stage',
        'reference_check','offer_sent','offer_signed'
    )),
    count          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS applicant_status_counts (
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
    period         TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN (
        'total_applicant','self_drop','rejected','in_progress'
    )),
    count          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS in_progress_stage_ratio (
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
    period         TEXT NOT NULL,
    stage          TEXT NOT NULL CHECK (stage IN (
        'application_review','screening_test','1st_interview',
        '2nd_interview','offer_sent','offer_signed'
    )),
    ratio          REAL NOT NULL  -- 0~1, 같은 (job_posting_id, period) 그룹 안에서 합 = 1.0
);

CREATE TABLE IF NOT EXISTS channel_stats (
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
    period         TEXT NOT NULL,
    channel        TEXT NOT NULL CHECK (channel IN (
        '직접지원','사내추천','지인추천','Direct Sourcing','산학협력','Lab'
    )),
    scope          TEXT NOT NULL CHECK (scope IN ('all_applicants','hired_only')),
    count          INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS department_stats (
    period          TEXT NOT NULL,
    department      TEXT NOT NULL,
    applicant_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_duration (
    job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
    department     TEXT NOT NULL,
    metric         TEXT NOT NULL CHECK (metric IN ('date_to_join','date_to_hire')),
    avg_days       REAL NOT NULL,
    period         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ytd_summary (
    year               INTEGER NOT NULL,
    department_scope   TEXT NOT NULL,  -- 'all' | 'Engineering' | ...
    joined_count       INTEGER NOT NULL,
    hired_count        INTEGER NOT NULL,
    avg_date_to_join   REAL NOT NULL,
    avg_date_to_hire   REAL NOT NULL,
    PRIMARY KEY (year, department_scope)
);

CREATE INDEX IF NOT EXISTS idx_funnel_period ON funnel_events(period);
CREATE INDEX IF NOT EXISTS idx_status_period ON applicant_status_counts(period);
CREATE INDEX IF NOT EXISTS idx_channel_period ON channel_stats(period, scope);
CREATE INDEX IF NOT EXISTS idx_dept_period ON department_stats(period);
