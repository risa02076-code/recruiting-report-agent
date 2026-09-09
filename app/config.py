"""환경변수 기반 설정. 민감정보(OpenAI/구글 API 키 등)는 .env로 관리."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DB_PATH = os.environ.get("RECRUITING_DB_PATH", str(BASE_DIR / "data" / "recruiting.db"))

# 우리 앱 자체의 운영 데이터(인사이트 초안/승인 상태 등). recruiting.db와 분리된 이유는
# app/generate_synthetic_data.py가 recruiting.db를 재생성 때마다 통째로 지우기 때문 —
# 에이전트 실행 결과는 그것과 무관하게 남아있어야 한다.
APP_DB_PATH = os.environ.get("APP_DB_PATH", str(BASE_DIR / "data" / "app_state.db"))

# Google Sheets (PRD 3.1) — kpi/detail/ytd(전부 판단 없는 고정 집계)만 여기 쓴다.
# 판단이 들어간 인사이트는 시트가 아니라 우리 DB(insight_drafts 테이블)에 저장하므로,
# 승인 전/후를 나누는 staging/published 분리가 필요 없다 — 시트는 1개면 충분하고
# generate_report_tabs.py가 매번 통째로 새로 써서 항상 최신 상태를 유지한다.
# 미설정 시 write_tab()이 로컬 파일로 폴백한다.
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
REPORT_SHEET_ID = os.environ.get("REPORT_SHEET_ID")
LOCAL_SHEET_FALLBACK_DIR = BASE_DIR / "data" / "sheet_local"  # 폴백 저장 위치

# 에이전트 루프 종료 조건 (PRD 4.3)
MAX_REQUERY_ROUNDS = int(os.environ.get("MAX_REQUERY_ROUNDS", "5"))
RUN_TIME_LIMIT_SECONDS = int(os.environ.get("RUN_TIME_LIMIT_SECONDS", "180"))

# 이상치 탐지 기본값 (PRD 4.2.1)
DEFAULT_SIGMA_MULTIPLIER = float(os.environ.get("DEFAULT_SIGMA_MULTIPLIER", "2"))
DEFAULT_BASELINE_PERIODS = int(os.environ.get("DEFAULT_BASELINE_PERIODS", "12"))

# 에이전트 루프가 쓸 모델. OPENAI_API_KEY는 openai SDK가 환경변수에서 직접 읽는다.
# 과정에서 배포한 키가 특정 모델만 허용할 수 있어 콘솔에서 사용 가능한 모델명을 확인해보는 것을 권장.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# 실행 이력 화면의 비용 추정치 계산용 (100만 토큰당 USD). 모델 요금이 바뀔 수 있으니
# 정확한 값은 platform.openai.com/pricing에서 확인 후 .env로 덮어쓸 것 — 여기 기본값은 대략치다.
OPENAI_INPUT_COST_PER_1M = float(os.environ.get("OPENAI_INPUT_COST_PER_1M", "0.15"))
OPENAI_OUTPUT_COST_PER_1M = float(os.environ.get("OPENAI_OUTPUT_COST_PER_1M", "0.6"))

# 승인된 리포트 화면에서 보여줄 Looker Studio 대시보드 링크 (사용자가 만들면 채워넣기).
LOOKER_STUDIO_URL = os.environ.get("LOOKER_STUDIO_URL", "")
