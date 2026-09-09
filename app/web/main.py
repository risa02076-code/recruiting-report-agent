"""
웹앱 — PRD 9장 화면 구성. FastAPI + 서버 렌더링(Jinja2)으로 최소한만 구현했다.

화면:
  GET  /                     대시보드 (기간 선택 → 리포트 생성, 최근 리포트 목록)
  POST /runs                 리포트 생성 트리거 → 백그라운드 스레드로 에이전트 실행 → 실행 상세로 이동
  GET  /runs/{run_id}        실행 상세 (실행 로그 + draft 인사이트 + 승인 버튼)
  POST /runs/{run_id}/approve  승인 (에이전트가 아니라 사람이 눌러야만 호출되는 유일한 경로)
  GET  /history               실행 이력 + 비용
  GET  /metrics               핵심지표/세부지표/연간누적지표 (판단 없는 고정 집계 숫자)

핵심지표 화면은 원래 Google Sheets + Looker Studio에 맡길 계획이었으나, 그러려면
사용자가 시트·서비스계정·대시보드 레이아웃을 전부 손으로 만들어야 해서(에이전트/과제
채점 기준과 무관한 순수 수작업) 대신 이 앱 안에서 바로 보여주는 것으로 단순화했다
(2026-09-09, 사용자 판단). generate_report_tabs.py/sheets_writer.py는 Sheets 연동을
원하면 여전히 쓸 수 있는 선택지로 남겨두되, 필수 경로에서는 뺐다.

실시간 로그는 웹소켓 대신 완료 전까지 2초마다 자동 새로고침하는 방식으로 단순화했다
(MVP 범위 — 진짜 스트리밍은 다음 단계 개선 과제).
"""
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.agent_loop import run_agent
from app.config import OPENAI_INPUT_COST_PER_1M, OPENAI_OUTPUT_COST_PER_1M
from app.generate_report_tabs import build_kpi_rows, build_detail_rows, build_ytd_rows
from app.insight_store import approve, get_draft
from app.web.pivot import pivot_kpi, pivot_long
import app.run_log_store as run_log_store

app = FastAPI(title="채용 리포트 자동 생성 에이전트")
_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def render(name: str, **context) -> HTMLResponse:
    # 이 환경의 설치된 fastapi/starlette 조합에서 Jinja2Templates.TemplateResponse()가
    # 내부적으로 unhashable-dict 오류를 내는 버전 호환 문제가 있어, 템플릿을 직접
    # 렌더링해서 우회한다 (Jinja2Templates.get_template()은 정상 동작 확인함).
    html = _templates.get_template(name).render(**context)
    return HTMLResponse(html)


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000 * OPENAI_INPUT_COST_PER_1M
            + output_tokens / 1_000_000 * OPENAI_OUTPUT_COST_PER_1M)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    runs = run_log_store.list_runs(limit=10)
    for r in runs:
        draft = get_draft(r["run_id"])
        r["draft_status"] = draft["status"] if draft else None
    return render("dashboard.html", runs=runs)


@app.post("/runs")
def create_run(period_start: str = Form(...), period_end: str = Form(...),
               department: str = Form("")):
    run_id = str(uuid.uuid4())
    filters = {"department": department} if department else {}
    period_label = period_start if period_start == period_end else f"{period_start}~{period_end}"

    # 백그라운드 스레드가 실제로 스케줄되기 전에 리다이렉트된 GET이 먼저 도착하면
    # run_id를 못 찾는 경쟁 상태가 생긴다 — 그래서 여기서 먼저 동기적으로 row를 만든다.
    run_log_store.start_run(run_id, period_label, filters)

    thread = threading.Thread(
        target=run_agent,
        kwargs={"period_start": period_start, "period_end": period_end,
                "filters": filters, "run_id": run_id},
        daemon=True,
    )
    thread.start()

    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: str):
    run = run_log_store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="해당 run_id를 찾을 수 없습니다.")
    events = run_log_store.get_events(run_id)
    draft = get_draft(run_id)
    estimated_cost = _estimate_cost(run["total_input_tokens"], run["total_output_tokens"])
    return render("run_detail.html", run=run, events=events, draft=draft,
                  estimated_cost=estimated_cost)


@app.post("/runs/{run_id}/approve")
def approve_run(run_id: str):
    try:
        approve(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="해당 run_id의 draft를 찾을 수 없습니다.")
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.get("/history", response_class=HTMLResponse)
def history():
    runs = run_log_store.list_runs(limit=100)
    total_input = total_output = 0
    for r in runs:
        total_input += r["total_input_tokens"]
        total_output += r["total_output_tokens"]
        r["estimated_cost"] = _estimate_cost(r["total_input_tokens"], r["total_output_tokens"])
        if r["finished_at"]:
            started = datetime.fromisoformat(r["started_at"])
            finished = datetime.fromisoformat(r["finished_at"])
            r["duration_s"] = round((finished - started).total_seconds(), 1)
        else:
            r["duration_s"] = None
    return render("history.html", runs=runs, total_input=total_input, total_output=total_output,
                  total_cost=_estimate_cost(total_input, total_output))


@app.get("/metrics", response_class=HTMLResponse)
def metrics():
    # 판단이 필요 없는 고정 집계라 DB에서 매번 다시 계산해서 보여준다 — 에이전트를
    # 거치지 않는다(app/generate_report_tabs.py와 같은 함수를 그대로 재사용).
    # 기간을 세로로 나열하면 추세가 안 보인다는 피드백으로, 기간을 가로축으로 돌리고
    # (pivot) 값 크기에 따라 배경색을 칠해(heatmap) 한 줄만 봐도 흐름이 보이게 한다.
    kpi_rows = build_kpi_rows()
    detail_rows = build_detail_rows()
    ytd_rows = build_ytd_rows()

    by_category = {"funnel": [], "department": [], "channel_all": [], "channel_hired": [], "in_progress": []}
    for row in detail_rows:
        if row["category"] == "channel":
            key = "channel_hired" if row["scope"] == "hired_only" else "channel_all"
            by_category[key].append(row)
        else:
            by_category[row["category"]].append(row)

    kpi_periods, kpi_table = pivot_kpi(kpi_rows)
    funnel_periods, funnel_table = pivot_long(by_category["funnel"])
    dept_periods, dept_table = pivot_long(by_category["department"])
    channel_all_periods, channel_all_table = pivot_long(by_category["channel_all"])
    channel_hired_periods, channel_hired_table = pivot_long(by_category["channel_hired"])
    progress_periods, progress_table = pivot_long(by_category["in_progress"])

    return render(
        "metrics.html", ytd_rows=ytd_rows,
        kpi_periods=kpi_periods, kpi_table=kpi_table,
        funnel_periods=funnel_periods, funnel_table=funnel_table,
        dept_periods=dept_periods, dept_table=dept_table,
        channel_all_periods=channel_all_periods, channel_all_table=channel_all_table,
        channel_hired_periods=channel_hired_periods, channel_hired_table=channel_hired_table,
        progress_periods=progress_periods, progress_table=progress_table,
    )
