"""
에이전트 루프 — PRD 4장. 계획 → 도구 호출 → 결과 관찰 → 다음 행동 결정을 반복한다.
OpenAI Chat Completions의 함수 호출(function calling)로 구현.

여기서 하는 일은 딱 세 가지 판단뿐이다(README "설계 원칙" 참고):
  1. 관리도로 봤을 때 이번 기간에 뭐가 이상치인지 판단
  2. 원인 파악을 위해 뭘 더 조회할지 계획
  3. 원인 분석 + 다음 조치 제안을 글로 쓰기

숫자 집계(kpi/detail/ytd)는 이 루프가 건드리지 않는다 — app/generate_report_tabs.py가 별도로 채운다.
이 루프의 유일한 쓰기 결과물은 write_insight_draft 도구를 통한 DB draft 저장 하나뿐이다.

종료 조건(PRD 4.3): query_recruiting_db 재조회 최대 MAX_REQUERY_ROUNDS회, 전체 실행 시간
RUN_TIME_LIMIT_SECONDS 초과 시 중단. 둘 다 프롬프트 지시가 아니라 코드로 강제한다.
"""
import json
import time
import uuid
from datetime import datetime, timezone

from openai import OpenAI

from app.config import OPENAI_MODEL, MAX_REQUERY_ROUNDS, RUN_TIME_LIMIT_SECONDS
from app.tools.query_recruiting_db import query_recruiting_db, QueryError
from app.tools.run_chart_code import run_chart_code, ChartCodeError
from app.tools.write_insight_draft import write_insight_draft
from app.insight_store import get_draft
from app.sheets_writer import SheetWriteError
import app.run_log_store as run_log_store

# 도구 호출 없이 텍스트로만 끝내려 하면서 아직 write_insight_draft를 안 부른 경우,
# 몇 번까지 "지금 저장하라"고 다시 요구할지. 너무 크면 무한루프에 가까워지니 작게 둔다.
MAX_NUDGES = 2

SYSTEM_PROMPT = """\
당신은 채용 리포트 자동 생성 에이전트입니다. 리크루터가 지정한 기간의 채용 데이터를 조사해서,
이번 기간에 주목할 만한 이상치가 있는지 판단하고, 있다면 원인을 조사한 뒤, 인사이트를 작성합니다.

절차:
1. query_recruiting_db로 기본 지표(퍼널, 상태별 현황 등)를 조회합니다. **이번 달만
   조회하지 말고, 처음부터 넉넉한 과거 범위(예: 이번 달 포함 최근 12개월)를
   period.start~period.end로 한 번에 조회하세요.** 여러 달을 걸치는 범위를 주면
   달마다 한 행씩(period 포함) 나뉘어 돌아오므로, 이 한 번의 호출로 관리도용
   시계열을 그대로 만들 수 있습니다. 절대 달마다 따로따로 호출하지 마세요 —
   재조회 횟수만 낭비하고 아무 이득이 없습니다.
2. 이상치를 판단할 때는 절대 "전월 대비 증감률"처럼 단순 비교를 쓰지 마세요. 반드시
   run_chart_code에 최근 여러 기간의 시계열(최소 3개, 이상적으로는 6개 이상)을
   넘겨서 관리도(평균±2표준편차) 기준으로 통계적으로 유의한 변화인지 확인한
   뒤에만 "이상치"라고 판단하세요.
3. 이상치가 발견되면, 원인을 좁히기 위해 추가로 어떤 축(부서별/채널별/단계별 등)으로
   쪼개서 봐야 할지 스스로 계획하고 query_recruiting_db를 다시 호출하세요(이때도
   필요하면 넓은 기간 범위로 한 번에). 이 재조회는 최대 5번까지만 허용됩니다 —
   그 안에 결론을 내리세요.
4. 이상치가 없다면 그 사실 자체를 인사이트로 남기세요("이번 기간은 특이사항 없음").
5. 조사가 끝나면 write_insight_draft를 정확히 한 번 호출해서 결론을 기록하세요.
   summary_text(핵심 요약), root_cause_text(원인 분석 — 반드시 조회한 숫자를 근거로
   인용할 것, 추측성 서술 금지), next_action_text(제안하는 다음 조치)를 채우세요.
6. write_insight_draft 호출 후에는 더 이상 도구를 호출하지 말고 짧은 마무리 문장만 남기세요.

숫자를 추측하지 마세요 — 모든 수치는 반드시 도구 호출 결과에서만 가져오세요.
"""

# 평가(eval/run_eval.py --prompt-variant)에서 baseline과 비교하는 프롬프트 변형.
# 2025-11(채널 이상치) 케이스를 baseline이 두 번 다 놓친 원인 — 퍼널 시계열만 보고
# 끝내버리는 습관 — 을 겨냥해서, 결론 내리기 전 다른 축을 최소 1번 보라고 못박았다.
SYSTEM_PROMPT_CHECK_AXIS = SYSTEM_PROMPT.replace(
    '4. 이상치가 없다면 그 사실 자체를 인사이트로 남기세요("이번 기간은 특이사항 없음").',
    '4. **"특이사항 없음"이라고 결론 내리기 전에, 반드시 퍼널 시계열 말고 다른 축(department 또는 '
    'channel, 특히 channel은 scope="hired_only"로) 중 최소 하나는 한 번 더 조회해서 거기서도 '
    '이상치가 없는지 확인하세요.** 퍼널만 보고 바로 "특이사항 없음"이라고 결론짓지 마세요. 다른 축까지 '
    "확인했는데도 이상치가 없다면 그 사실을 인사이트로 남기세요.",
)

PROMPT_VARIANTS = {
    "baseline": SYSTEM_PROMPT,
    "check_axis": SYSTEM_PROMPT_CHECK_AXIS,
}

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "query_recruiting_db",
            "description": (
                "채용 집계 데이터를 조회한다. 구체적인 숫자가 필요할 때마다 호출하고, "
                "절대 값을 추측하지 않는다. 결과가 비어 있으면 해당 기간에 데이터가 없다는 뜻이다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "object",
                        "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
                        "required": ["start", "end"],
                        "description": "YYYY-MM 형식",
                    },
                    "metric": {
                        "type": "string",
                        "enum": ["funnel", "status_counts", "in_progress_ratio", "channel",
                                 "department", "stage_duration", "ytd_summary"],
                    },
                    "filters": {
                        "type": "object",
                        "properties": {
                            "department": {"type": "string"},
                            "job_posting_id": {"type": "string"},
                            "channel": {"type": "string"},
                        },
                    },
                    "scope": {"type": "string", "enum": ["all_applicants", "hired_only"]},
                },
                "required": ["period", "metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_chart_code",
            "description": (
                "과거 여러 기간의 지표 값 목록을 넣으면, 관리도(평균±sigma_multiplier*표준편차) "
                "기준으로 이번 기간이 통계적으로 유의한 이상치인지 판단해준다. 단순 증감률만으로 "
                "이상치라고 말하지 말고, 반드시 이 도구로 검증한 뒤에만 이상치라고 말한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_series": {
                        "type": "array", "items": {"type": "number"},
                        "description": "과거 기간들의 값. 마지막 값이 이번 기간이다.",
                    },
                    "sigma_multiplier": {"type": "number", "description": "기본 2"},
                },
                "required": ["metric_series"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_insight_draft",
            "description": (
                "이상치 판단과 원인 조사가 끝난 뒤, 그 결론을 딱 한 번 기록한다. 항상 초안(draft) "
                "상태로만 저장되며, 호출한다고 해서 리크루터에게 바로 노출되지 않는다 — 사람이 "
                "앱에서 승인해야 확정된다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string"},
                    "summary_text": {"type": "string"},
                    "root_cause_text": {"type": "string"},
                    "next_action_text": {"type": "string"},
                },
                "required": ["period", "summary_text", "root_cause_text", "next_action_text"],
            },
        },
    },
]


class RunAborted(Exception):
    pass


def _dispatch_tool(name: str, tool_input: dict, run_id: str, query_round_count: list) -> dict:
    if name == "query_recruiting_db":
        if query_round_count[0] >= MAX_REQUERY_ROUNDS:
            raise RunAborted(
                f"query_recruiting_db 최대 호출 횟수({MAX_REQUERY_ROUNDS}회)를 넘었습니다. "
                "지금까지 조사한 내용으로 write_insight_draft를 호출해 결론을 내리세요."
            )
        query_round_count[0] += 1
        return query_recruiting_db(**tool_input)

    if name == "run_chart_code":
        return run_chart_code(**tool_input)

    if name == "write_insight_draft":
        generated_at = datetime.now(timezone.utc).isoformat()
        return write_insight_draft(run_id=run_id, generated_at=generated_at, **tool_input)

    raise RunAborted(f"알 수 없는 도구입니다: {name}")


def _run_loop(run_id: str, messages: list, query_round_count: int, step_no: int,
              wrote_draft: bool, nudge_count: int, start_time: float,
              max_iterations: int | None = None) -> dict:
    """실제 루프 본체. run_agent()(새로 시작)와 resume_run()(이어서 시작) 둘 다 이 함수를
    호출한다 — 시작 방식만 다르고 진행 로직은 완전히 같아야 재개가 의미 있기 때문이다.

    max_iterations는 테스트 전용이다: 지정한 횟수만큼만 API를 호출하고, 아직 안 끝났으면
    status를 확정 짓지 않고(= 'running'으로 남겨) 그대로 반환한다 — 실제로 프로세스가 죽었을
    때와 똑같은 상태를 만들어서 resume_run()이 이어받을 수 있는지 테스트하기 위함이다."""
    client = OpenAI()
    round_box = [query_round_count]  # _dispatch_tool과 공유하려고 리스트로 감쌈(참조 전달)
    status = "completed"
    iterations = 0

    try:
        while True:
            if time.monotonic() - start_time > RUN_TIME_LIMIT_SECONDS:
                status = "timeout"
                run_log_store.log_event(run_id, step_no, "error",
                                         reasoning_text=f"시간 제한({RUN_TIME_LIMIT_SECONDS}초) 초과로 중단")
                break
            if max_iterations is not None and iterations >= max_iterations:
                run_log_store.save_messages(run_id, messages)
                return {"run_id": run_id, "status": "running", "wrote_draft": wrote_draft,
                        "note": f"테스트용 중단(max_iterations={max_iterations}) — 재개 가능한 상태로 남음"}
            iterations += 1

            response = client.chat.completions.create(
                model=OPENAI_MODEL, messages=messages, tools=TOOL_SPECS, tool_choice="auto",
            )
            usage = response.usage
            run_log_store.add_token_usage(run_id, usage.prompt_tokens, usage.completion_tokens)

            msg = response.choices[0].message
            if msg.content:
                step_no += 1
                run_log_store.log_event(run_id, step_no, "agent_text", reasoning_text=msg.content)

            if not msg.tool_calls:
                if wrote_draft:
                    break  # 이미 저장했고, 이제 진짜 마무리 인사만 남은 상태
                if nudge_count >= MAX_NUDGES:
                    break  # 계속 찔러봐도 저장을 안 하면 실패로 종결(아래에서 처리)
                # 도구 호출 없이 텍스트로만 "~해야 한다"고 말하고 멈추는 경우가 있었다
                # (2026-09-09 실제 발견: 원인 분석까지 다 해놓고 write_insight_draft를
                # 안 부르고 끝남 → 성과가 있는데도 failed 처리됨). 그냥 끝내지 말고
                # 지금 바로 저장하라고 한 번 더 요구한다.
                nudge_count += 1
                messages.append({"role": "assistant", "content": msg.content})
                messages.append({
                    "role": "user",
                    "content": (
                        "아직 write_insight_draft를 호출하지 않았습니다. 더 조사하고 싶더라도 "
                        "재조회 한도를 고려해, 지금까지 조사한 내용만으로 write_insight_draft를 "
                        "지금 바로 호출해 결론을 기록하세요."
                    ),
                })
                run_log_store.save_messages(run_id, messages)
                continue

            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })

            for tool_call in msg.tool_calls:
                step_no += 1
                t0 = time.monotonic()
                try:
                    tool_input = json.loads(tool_call.function.arguments)
                    result = _dispatch_tool(tool_call.function.name, tool_input, run_id, round_box)
                except (QueryError, ChartCodeError, SheetWriteError, RunAborted,
                        TypeError, json.JSONDecodeError) as e:
                    result = {"error": str(e)}
                latency_ms = int((time.monotonic() - t0) * 1000)

                run_log_store.log_event(
                    run_id, step_no, "tool_call", tool_name=tool_call.function.name,
                    tool_input=json.loads(tool_call.function.arguments) if tool_call.function.arguments else {},
                    tool_output=result, latency_ms=latency_ms,
                )
                if tool_call.function.name == "write_insight_draft" and "error" not in result:
                    wrote_draft = True

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            run_log_store.save_messages(run_id, messages)  # 턴 하나 끝날 때마다 재개용 스냅샷 갱신

        if status == "completed" and not wrote_draft:
            status = "failed"
            run_log_store.log_event(run_id, step_no + 1, "error",
                                     reasoning_text="write_insight_draft를 한 번도 호출하지 않고 종료됨")
    except Exception as e:
        status = "failed"
        run_log_store.log_event(run_id, step_no + 1, "error", reasoning_text=f"예외 발생: {e}")

    run_log_store.finish_run(run_id, status)
    return {"run_id": run_id, "status": status, "wrote_draft": wrote_draft}


def run_agent(period_start: str, period_end: str, filters: dict | None = None,
              run_id: str | None = None, system_prompt: str | None = None,
              max_iterations: int | None = None) -> dict:
    """에이전트 루프를 처음부터 실행. period_start/period_end는 YYYY-MM.

    run_id를 미리 만들어 넘길 수 있게 한 이유: 웹앱이 백그라운드 스레드로 이 함수를 실행하기
    전에 run_id를 먼저 알아야 바로 /runs/{run_id} 화면으로 이동시켜 진행 상황을 보여줄 수 있다.
    system_prompt를 넘기면 기본 SYSTEM_PROMPT 대신 그걸 쓴다 — 평가 세트에서 프롬프트를
    바꿔가며 성능을 비교할 때 씀(eval/run_eval.py --prompt-variant, PRD 10.2)."""
    run_id = run_id or str(uuid.uuid4())
    filters = filters or {}
    period_label = period_start if period_start == period_end else f"{period_start}~{period_end}"
    prompt = system_prompt or SYSTEM_PROMPT

    run_log_store.start_run(run_id, period_label, filters)

    user_prompt = (
        f"기간: {period_start} ~ {period_end}\n"
        f"필터: {json.dumps(filters, ensure_ascii=False) if filters else '없음'}\n"
        "이 기간의 채용 현황을 조사하고, 이상치가 있다면 원인을 분석해 인사이트를 작성하세요."
    )
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_prompt},
    ]
    run_log_store.save_messages(run_id, messages)

    return _run_loop(run_id, messages, query_round_count=0, step_no=0, wrote_draft=False,
                      nudge_count=0, start_time=time.monotonic(), max_iterations=max_iterations)


def resume_run(run_id: str, max_iterations: int | None = None) -> dict:
    """중단된(status='running') run을 저장된 대화 상태에서 이어서 실행한다 (PRD 4.4).

    query_round_count는 runs.query_round_count(도구 호출마다 이미 자동 증가되던 값)를,
    wrote_draft는 insight_drafts에 해당 run_id의 draft가 이미 있는지를 보고 재구성한다.
    nudge_count는 별도로 저장해두지 않아 0부터 다시 세는데, 최악의 경우에도 "저장하라"고
    최대 2번 더 요구하는 정도라 크게 문제되지 않는다(간소화 지점, README에 명시).
    시간 제한은 재개 시점부터 새로 3분을 준다 — 크래시로 멈춰있던 시간까지 실행 시간에
    포함시키는 건 의미가 없다고 판단."""
    run = run_log_store.get_run(run_id)
    if run is None:
        raise ValueError(f"run_id를 찾을 수 없습니다: {run_id}")
    if run["status"] != "running":
        raise ValueError(f"이 run은 이미 '{run['status']}' 상태라 재개할 수 없습니다(진행 중인 것만 재개 가능).")

    messages = run_log_store.load_messages(run_id)
    if not messages:
        raise ValueError("저장된 대화 상태가 없어 재개할 수 없습니다 — 처음부터 다시 실행하세요.")

    events = run_log_store.get_events(run_id)
    step_no = max((e["step_no"] for e in events), default=0)
    wrote_draft = get_draft(run_id) is not None

    return _run_loop(run_id, messages, query_round_count=run["query_round_count"], step_no=step_no,
                      wrote_draft=wrote_draft, nudge_count=0, start_time=time.monotonic(),
                      max_iterations=max_iterations)


if __name__ == "__main__":
    import sys
    start = sys.argv[1] if len(sys.argv) > 1 else "2026-03"
    end = sys.argv[2] if len(sys.argv) > 2 else start
    print(run_agent(start, end))
