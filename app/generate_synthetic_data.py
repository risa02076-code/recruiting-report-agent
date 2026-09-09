"""
합성 채용 데이터 생성기.

PRD.md 3장 스키마를 채우는 24개월치(2024-09 ~ 2026-08) 가짜 데이터를 만들어
data/recruiting.db(SQLite)에 적재한다. 개인 식별 정보는 전혀 포함하지 않는다
(공고 단위 집계값만 생성).

의도적으로 2개의 이상치를 주입해 data/synthetic/anomaly_log.json에 기록해둔다.
나중에 평가(PRD 10장) 단계에서 "에이전트가 이 이상치를 실제로 찾아내는지"를
채점하는 골든 정답으로 쓴다.
"""
import json
import random
import sqlite3
from pathlib import Path

from app.config import DB_PATH, BASE_DIR

random.seed(42)

DEPARTMENTS = ["Engineering", "Business", "IT/DATA", "Management Control", "P&C"]
DEPARTMENT_WEIGHTS = [0.431, 0.403, 0.125, 0.025, 0.016]

CHANNELS = ["직접지원", "지인추천", "Direct Sourcing", "사내추천", "산학협력", "Lab"]
CHANNEL_WEIGHTS_ALL = [0.583, 0.165, 0.121, 0.11, 0.013, 0.008]
CHANNEL_WEIGHTS_HIRED = [0.188, 0.141, 0.176, 0.459, 0.036, 0.0]

IN_PROGRESS_STAGES = [
    "application_review", "screening_test", "1st_interview",
    "2nd_interview", "offer_sent", "offer_signed",
]
IN_PROGRESS_WEIGHTS = [0.556, 0.167, 0.056, 0.056, 0.056, 0.109]

FUNNEL_STAGES = [
    "application_stage", "sc_stage", "interview_stage",
    "reference_check", "offer_sent", "offer_signed",
]

# 24개월: 2024-09 ~ 2026-08
def month_range(start_year=2024, start_month=9, n=24):
    periods = []
    y, m = start_year, start_month
    for _ in range(n):
        periods.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return periods

PERIODS = month_range()

# 의도적으로 주입하는 이상치 2건 (평가셋 골든 정답용)
ANOMALY_OFFER_DROP_PERIOD = "2026-03"      # 오퍼 발송->수락 전환율 급락
ANOMALY_CHANNEL_SPIKE_PERIOD = "2025-11"   # Direct Sourcing 채널의 "합격자만" 비중 급등


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def multinomial_split(total, weights):
    """total을 weights 비율로 나누되 합이 total과 정확히 일치하게 만든다."""
    if total <= 0:
        return [0] * len(weights)
    raw = [total * w for w in weights]
    counts = [int(r) for r in raw]
    remainder = total - sum(counts)
    # 나머지는 소수부가 큰 순서대로 1씩 배분
    fracs = sorted(range(len(weights)), key=lambda i: raw[i] - counts[i], reverse=True)
    for i in range(remainder):
        counts[fracs[i % len(weights)]] += 1
    return counts


def make_job_postings():
    postings = []
    pid = 1
    for period in PERIODS:
        # 월별 표본이 너무 적으면(2~4건) 오퍼수락률 같은 비율 지표가 통계적으로
        # 너무 들쭉날쭉해져서, 의도적으로 주입한 이상치가 노이즈에 묻혀버린다.
        # 관리도가 신호와 노이즈를 구분할 수 있으려면 월별 표본이 어느 정도 있어야 한다.
        n_postings = random.randint(6, 10)
        for _ in range(n_postings):
            dept = random.choices(DEPARTMENTS, weights=DEPARTMENT_WEIGHTS, k=1)[0]
            channel_default = random.choices(CHANNELS, weights=CHANNEL_WEIGHTS_ALL, k=1)[0]
            year, month = map(int, period.split("-"))
            postings.append({
                "id": f"JP{pid:04d}",
                "title": f"{dept} Req {pid}",
                "department": dept,
                "channel_default": channel_default,
                "opened_date": f"{year:04d}-{month:02d}-01",
                "closed_date": None,
                "period": period,
            })
            pid += 1
    return postings


def generate_posting_funnel(posting):
    dept = posting["department"]
    period = posting["period"]

    base_total = {"Engineering": 45, "Business": 42, "IT/DATA": 20,
                  "Management Control": 12, "P&C": 10}[dept]
    total_applicant = max(5, int(random.gauss(base_total, base_total * 0.25)))

    r_sc = random.uniform(0.25, 0.50)
    r_interview = random.uniform(0.40, 0.70)
    r_ref = random.uniform(0.35, 0.75)
    r_offer_sent = random.uniform(0.55, 0.95)
    r_offer_signed = random.uniform(0.45, 0.85)

    # 이상치 1: 오퍼 수락률(offer_sent -> offer_signed) 급락
    if period == ANOMALY_OFFER_DROP_PERIOD:
        r_offer_signed = random.uniform(0.15, 0.30)

    sc_stage = int(total_applicant * r_sc)
    interview_stage = int(sc_stage * r_interview)
    reference_check = int(interview_stage * r_ref)
    offer_sent = int(reference_check * r_offer_sent) if reference_check > 0 else int(interview_stage * 0.3)
    offer_signed = int(offer_sent * r_offer_signed)

    funnel = {
        "application_stage": total_applicant,
        "sc_stage": sc_stage,
        "interview_stage": interview_stage,
        "reference_check": reference_check,
        "offer_sent": offer_sent,
        "offer_signed": offer_signed,
    }

    self_drop = int(total_applicant * random.uniform(0.05, 0.15))
    in_progress = int(total_applicant * random.uniform(0.05, 0.20))
    hired = offer_signed

    if self_drop + in_progress + hired > total_applicant:
        in_progress = clamp(total_applicant - self_drop - hired, 0, total_applicant)
    rejected = clamp(total_applicant - self_drop - in_progress - hired, 0, total_applicant)

    status_counts = {
        "total_applicant": total_applicant,
        "self_drop": self_drop,
        "rejected": rejected,
        "in_progress": in_progress,
    }

    return funnel, status_counts, hired, in_progress


def generate_channel_rows(posting, total_applicant, hired):
    period = posting["period"]
    hired_weights = list(CHANNEL_WEIGHTS_HIRED)

    # 이상치 2: 이 기간엔 "합격자만" 기준으로 Direct Sourcing 비중이 급등
    if period == ANOMALY_CHANNEL_SPIKE_PERIOD:
        hired_weights = [0.12, 0.08, 0.55, 0.20, 0.05, 0.0]

    all_counts = multinomial_split(total_applicant, CHANNEL_WEIGHTS_ALL)
    hired_counts = multinomial_split(hired, hired_weights)

    rows = []
    for ch, cnt in zip(CHANNELS, all_counts):
        rows.append((posting["id"], period, ch, "all_applicants", cnt))
    for ch, cnt in zip(CHANNELS, hired_counts):
        rows.append((posting["id"], period, ch, "hired_only", cnt))
    return rows


def generate_in_progress_ratio_rows(posting, in_progress):
    if in_progress <= 0:
        return []
    counts = multinomial_split(100, IN_PROGRESS_WEIGHTS)  # 100분율로 뽑아 비율로 환산
    rows = []
    for stage, cnt in zip(IN_PROGRESS_STAGES, counts):
        ratio = round(cnt / 100.0, 4)
        if ratio > 0:
            rows.append((posting["id"], posting["period"], stage, ratio))
    return rows


def generate_stage_duration_rows(posting, hired):
    if hired <= 0:
        return []
    dept_offset = {"Engineering": 8, "Business": 0, "IT/DATA": 4,
                   "Management Control": 2, "P&C": 0}[posting["department"]]
    date_to_hire = round(35 + dept_offset + random.uniform(-8, 8), 1)
    date_to_join = round(date_to_hire + 25 + random.uniform(-5, 10), 1)
    return [
        (posting["id"], posting["department"], "date_to_hire", date_to_hire, posting["period"]),
        (posting["id"], posting["department"], "date_to_join", date_to_join, posting["period"]),
    ]


def build_database():
    postings = make_job_postings()

    job_postings_rows = []
    funnel_rows = []
    status_rows = []
    channel_rows = []
    in_progress_rows = []
    stage_duration_rows = []
    dept_agg = {}  # (period, department) -> applicant_count

    for p in postings:
        job_postings_rows.append((p["id"], p["title"], p["department"],
                                   p["channel_default"], p["opened_date"], p["closed_date"]))

        funnel, status_counts, hired, in_progress = generate_posting_funnel(p)
        for stage, cnt in funnel.items():
            funnel_rows.append((p["id"], p["period"], stage, cnt))
        for status, cnt in status_counts.items():
            status_rows.append((p["id"], p["period"], status, cnt))

        channel_rows.extend(generate_channel_rows(p, status_counts["total_applicant"], hired))
        in_progress_rows.extend(generate_in_progress_ratio_rows(p, in_progress))
        stage_duration_rows.extend(generate_stage_duration_rows(p, hired))

        key = (p["period"], p["department"])
        dept_agg[key] = dept_agg.get(key, 0) + status_counts["total_applicant"]

    department_rows = [(period, dept, cnt) for (period, dept), cnt in dept_agg.items()]

    # ytd_summary: 연도별로 hired/joined/평균소요일 집계 (전체 + Engineering만)
    ytd_rows = compute_ytd(postings, stage_duration_rows)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    schema_sql = (Path(__file__).parent / "db_schema.sql").read_text(encoding="utf-8")
    cur.executescript(schema_sql)

    cur.executemany(
        "INSERT INTO job_postings VALUES (?,?,?,?,?,?)", job_postings_rows)
    cur.executemany(
        "INSERT INTO funnel_events VALUES (?,?,?,?)", funnel_rows)
    cur.executemany(
        "INSERT INTO applicant_status_counts VALUES (?,?,?,?)", status_rows)
    cur.executemany(
        "INSERT INTO channel_stats VALUES (?,?,?,?,?)", channel_rows)
    cur.executemany(
        "INSERT INTO in_progress_stage_ratio VALUES (?,?,?,?)", in_progress_rows)
    cur.executemany(
        "INSERT INTO stage_duration VALUES (?,?,?,?,?)", stage_duration_rows)
    cur.executemany(
        "INSERT INTO department_stats VALUES (?,?,?)", department_rows)
    cur.executemany(
        "INSERT INTO ytd_summary VALUES (?,?,?,?,?,?)", ytd_rows)

    conn.commit()
    conn.close()

    write_anomaly_log()

    print(f"OK: {len(job_postings_rows)} job postings, {len(funnel_rows)} funnel rows, "
          f"{len(channel_rows)} channel rows written to {DB_PATH}")


def compute_ytd(postings, stage_duration_rows):
    by_posting_metric = {}
    for jp_id, dept, metric, avg_days, period in stage_duration_rows:
        by_posting_metric.setdefault(jp_id, {})[metric] = avg_days

    postings_by_id = {p["id"]: p for p in postings}
    years = sorted({int(p.split("-")[0]) for p in PERIODS})

    rows = []
    for year in years:
        for scope in ["all", "Engineering"]:
            hire_days, join_days, hired_count = [], [], 0
            for jp_id, metrics in by_posting_metric.items():
                p = postings_by_id[jp_id]
                if not p["period"].startswith(str(year)):
                    continue
                if scope == "Engineering" and p["department"] != "Engineering":
                    continue
                if "date_to_hire" in metrics:
                    hire_days.append(metrics["date_to_hire"])
                    hired_count += 1
                if "date_to_join" in metrics:
                    join_days.append(metrics["date_to_join"])
            avg_hire = round(sum(hire_days) / len(hire_days), 2) if hire_days else 0.0
            avg_join = round(sum(join_days) / len(join_days), 2) if join_days else 0.0
            rows.append((year, scope, hired_count, hired_count, avg_join, avg_hire))
    return rows


def write_anomaly_log():
    out_dir = BASE_DIR / "data" / "synthetic"
    out_dir.mkdir(parents=True, exist_ok=True)
    log = [
        {
            "period": ANOMALY_OFFER_DROP_PERIOD,
            "metric": "offer_sent -> offer_signed 전환율",
            "expected_direction": "급락",
            "reason": "합성 데이터에 의도적으로 주입한 오퍼 수락률 급락 (평가셋 골든 정답용)",
        },
        {
            "period": ANOMALY_CHANNEL_SPIKE_PERIOD,
            "metric": "channel_stats scope=hired_only 중 Direct Sourcing 비중",
            "expected_direction": "급등",
            "reason": "전체 지원자 채널 분포는 그대로인데 합격자만 놓고 보면 Direct Sourcing 비중이 급등 "
                      "(지원경로 vs 합격자 지원경로 격차 탐지 시나리오, PRD 9.1 참고)",
        },
    ]
    (out_dir / "anomaly_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    if Path(DB_PATH).exists():
        Path(DB_PATH).unlink()
    build_database()
