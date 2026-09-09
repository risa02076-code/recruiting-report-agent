"""
평가 실행기 — PRD.md 10장.

eval/cases.py의 각 케이스에 대해 에이전트를 실행(또는 이미 실행된 결과가 있으면 재사용해서
비용 절약)하고, 완료 여부/정확도(골든 키워드·오탐)/환각 의심/재조회 횟수/소요시간/토큰/비용을
채점해 표로 출력하고 eval/results/에 CSV로 남긴다.

실행 비용에 주의: --fresh를 주면 이미 있는 run을 무시하고 전부 새로 호출한다(실제 과금 발생).
기본값(옵션 없음)은 같은 기간의 완료된 run이 이미 있으면 재사용한다.

사용법:
    python -m eval.run_eval                              # baseline, 기존 run 재사용
    python -m eval.run_eval --fresh                       # baseline, 전부 새로 실행
    python -m eval.run_eval --prompt-variant check_axis    # 다른 프롬프트로 비교 실행(항상 새로 호출)

설정 비교(PRD 10장 "비교표"): --prompt-variant로 app/agent_loop.py의 PROMPT_VARIANTS 중 하나를
골라 같은 골든 케이스에 대해 실행하면, eval/results/의 CSV 두 개(baseline vs 변형)를 나란히
놓고 정확도·비용·재조회횟수 변화를 비교할 수 있다. baseline이 아닌 변형은 캐시를 신뢰할 수
없으므로(다른 설정이라 다른 결과가 나와야 정상) 항상 새로 실행한다.
"""
import argparse
import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from app.agent_loop import run_agent, PROMPT_VARIANTS
from app.config import OPENAI_INPUT_COST_PER_1M, OPENAI_OUTPUT_COST_PER_1M, OPENAI_MODEL
from app.insight_store import get_draft
import app.run_log_store as run_log_store

from eval.cases import EVAL_CASES, FALSE_POSITIVE_MARKERS

RESULTS_DIR = Path(__file__).parent / "results"


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000 * OPENAI_INPUT_COST_PER_1M
            + output_tokens / 1_000_000 * OPENAI_OUTPUT_COST_PER_1M)


def _period_label(start: str, end: str) -> str:
    return start if start == end else f"{start}~{end}"


def find_existing_run(period_start: str, period_end: str) -> dict | None:
    label = _period_label(period_start, period_end)
    for run in run_log_store.list_runs(limit=200):
        if run["period"] == label and run["status"] == "completed":
            return run  # list_runs는 started_at DESC이므로 가장 최근 것
    return None


def grade_case(case: dict, run: dict | None, draft: dict | None) -> dict:
    result = {
        "case_id": case["case_id"], "period": case["period_start"],
        "expects_anomaly": case["expects_anomaly"], "run_id": run["run_id"] if run else None,
        "completed": False, "correct": False, "note": "", "hallucination_suspects": [],
        "query_round_count": None, "duration_s": None,
        "input_tokens": None, "output_tokens": None, "estimated_cost": None, "status": None,
    }
    if run is None:
        result["note"] = "실행 실패(run 없음)"
        return result

    result["status"] = run["status"]
    result["query_round_count"] = run["query_round_count"]
    result["input_tokens"] = run["total_input_tokens"]
    result["output_tokens"] = run["total_output_tokens"]
    result["estimated_cost"] = round(_estimate_cost(run["total_input_tokens"], run["total_output_tokens"]), 4)
    if run["finished_at"]:
        started = datetime.fromisoformat(run["started_at"])
        finished = datetime.fromisoformat(run["finished_at"])
        result["duration_s"] = round((finished - started).total_seconds(), 1)

    completed = run["status"] == "completed" and draft is not None
    result["completed"] = completed
    if not completed:
        result["note"] = f"미완료(status={run['status']})"
        return result

    combined = f"{draft['summary_text']} {draft['root_cause_text']} {draft['next_action_text']}"

    if case["expects_anomaly"]:
        missing_kw = [kw for kw in case["golden_keywords"] if kw.lower() not in combined.lower()]
        result["correct"] = not missing_kw
        if missing_kw:
            result["note"] = f"골든 키워드 누락: {missing_kw}"
    else:
        hit_markers = [m for m in FALSE_POSITIVE_MARKERS if m in combined]
        result["correct"] = not hit_markers
        if hit_markers:
            result["note"] = f"오탐 의심(근거 표현: {hit_markers})"

    events = run_log_store.get_events(run["run_id"])
    tool_output_blob = " ".join(e["tool_output_json"] or "" for e in events if e["event_type"] == "tool_call")
    numbers = set(re.findall(r"\d+\.\d+|\d+", draft["root_cause_text"]))
    significant = {n for n in numbers if len(n.replace(".", "")) >= 2}  # 0,1 같은 흔한 숫자는 제외
    result["hallucination_suspects"] = sorted(n for n in significant if n not in tool_output_blob)

    return result


def run_all(fresh: bool, variant: str) -> list:
    # baseline이 아닌 변형은 이전 캐시(다른 프롬프트로 만들어진 결과)를 재사용하면 비교가
    # 무의미해지므로 항상 새로 실행한다. baseline만 비용 절약을 위해 재사용을 허용.
    reuse_allowed = (not fresh) and variant == "baseline"
    system_prompt = PROMPT_VARIANTS[variant]

    results = []
    for case in EVAL_CASES:
        run = find_existing_run(case["period_start"], case["period_end"]) if reuse_allowed else None
        if run:
            print(f"[{case['case_id']}] 기존 run 재사용 (run_id={run['run_id'][:8]}) — 추가 비용 없음")
        else:
            print(f"[{case['case_id']}] 에이전트 새로 실행 중... ({case['period_start']}, variant={variant})")
            summary = run_agent(case["period_start"], case["period_end"], system_prompt=system_prompt)
            run = run_log_store.get_run(summary["run_id"])
        draft = get_draft(run["run_id"]) if run else None
        results.append(grade_case(case, run, draft))
    return results


def print_table(results: list) -> None:
    header = f"{'case_id':<38} {'완료':<5} {'정답':<5} {'재조회':<6} {'소요(s)':<8} {'비용($)':<9} note"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['case_id']:<38} {str(r['completed']):<5} {str(r['correct']):<5} "
              f"{str(r['query_round_count']):<6} {str(r['duration_s']):<8} "
              f"{str(r['estimated_cost']):<9} {r['note']}")
        if r["hallucination_suspects"]:
            print(f"    ⚠ 환각 의심 숫자(도구 결과에 없음): {r['hallucination_suspects']}")


def print_summary(results: list) -> None:
    n = len(results)
    completed = sum(r["completed"] for r in results)
    correct = sum(r["correct"] for r in results)
    total_cost = sum(r["estimated_cost"] or 0 for r in results)
    rounds = [r["query_round_count"] for r in results if r["query_round_count"] is not None]
    avg_rounds = sum(rounds) / len(rounds) if rounds else 0
    print(f"\n=== 요약 (모델: {OPENAI_MODEL}) ===")
    print(f"작업 완료율: {completed}/{n} ({completed/n:.0%})")
    print(f"정확도(이상치 판단): {correct}/{n} ({correct/n:.0%})")
    print(f"평균 재조회 횟수: {avg_rounds:.1f}")
    print(f"총 추정 비용: ${total_cost:.4f}")


def write_csv(results: list, label: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = RESULTS_DIR / f"{ts}_{label}.csv"
    fieldnames = ["case_id", "period", "expects_anomaly", "run_id", "status", "completed", "correct",
                  "query_round_count", "duration_s", "input_tokens", "output_tokens",
                  "estimated_cost", "hallucination_suspects", "note"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = dict(r)
            row["hallucination_suspects"] = ";".join(row["hallucination_suspects"])
            writer.writerow(row)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true", help="기존 run을 무시하고 전부 새로 실행(과금 발생)")
    parser.add_argument("--prompt-variant", default="baseline", choices=list(PROMPT_VARIANTS),
                         help="app/agent_loop.py의 PROMPT_VARIANTS 중 어떤 프롬프트로 실행할지")
    parser.add_argument("--label", default=None, help="결과 파일명에 붙일 라벨(기본값: prompt-variant 이름)")
    args = parser.parse_args()

    label = args.label or args.prompt_variant
    all_results = run_all(fresh=args.fresh, variant=args.prompt_variant)
    print()
    print_table(all_results)
    print_summary(all_results)
    csv_path = write_csv(all_results, label)
    print(f"\n결과 저장: {csv_path}")
