"""
평가 세트 — PRD.md 10장.

data/synthetic/anomaly_log.json에 의도적으로 주입해둔 이상치 2건을 "정답이 있는" 케이스로,
그 외 정상 기간 몇 개를 "이상치 없음이 정답인" 케이스(오탐 여부 확인용)로 삼는다.

정상 기간을 고를 때 2024-09 시작 시점 바로 다음 달들은 피했다 — 관리도 계산에 최소 3개,
현실적으로 6개 이상의 과거 기간이 필요한데 시작 직후는 baseline이 너무 얇아서 정상/비정상
판단 자체가 불안정해진다.
"""

EVAL_CASES = [
    {
        "case_id": "anomaly_offer_signed_drop",
        "period_start": "2026-03",
        "period_end": "2026-03",
        "expects_anomaly": True,
        "golden_keywords": ["offer_signed"],
        "golden_note": "2026-03: 오퍼 발송 대비 수락(offer_signed)이 0으로 급락 (관리도 상 이상치)",
    },
    {
        "case_id": "anomaly_channel_direct_sourcing_spike",
        "period_start": "2025-11",
        "period_end": "2025-11",
        "expects_anomaly": True,
        "golden_keywords": ["Direct Sourcing"],
        "golden_note": (
            "2025-11: 합격자 기준(hired_only) Direct Sourcing 채널 비중 급등. "
            "전체 지원자 채널 분포는 정상이라 채널별 breakdown을 실제로 조회해야만 보인다 — "
            "퍼널만 보고 끝내면 놓치는 게 정상(알려진 어려운 케이스, README 참고)."
        ),
    },
    {
        "case_id": "normal_2025_05",
        "period_start": "2025-05", "period_end": "2025-05",
        "expects_anomaly": False,
        "golden_keywords": [],
        "golden_note": "이상치 미주입 기간 — 오탐(false positive) 여부 확인용",
    },
    {
        "case_id": "normal_2025_07",
        "period_start": "2025-07", "period_end": "2025-07",
        "expects_anomaly": False,
        "golden_keywords": [],
        "golden_note": "이상치 미주입 기간 — 오탐(false positive) 여부 확인용",
    },
    {
        "case_id": "normal_2025_09",
        "period_start": "2025-09", "period_end": "2025-09",
        "expects_anomaly": False,
        "golden_keywords": [],
        "golden_note": "이상치 미주입 기간 — 오탐(false positive) 여부 확인용",
    },
    {
        "case_id": "normal_2026_01",
        "period_start": "2026-01", "period_end": "2026-01",
        "expects_anomaly": False,
        "golden_keywords": [],
        "golden_note": "이상치 미주입 기간 — 오탐(false positive) 여부 확인용",
    },
]

# 정상 기간에서 이 표현이 나오면 "근거 없이 이상치라고 우겼다"(오탐)로 간주한다.
FALSE_POSITIVE_MARKERS = ["이상치를 발견", "이상치가 발견", "통계적으로 유의한 이상", "급락", "급등", "위기"]
