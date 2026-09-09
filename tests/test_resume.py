"""
재개(resume) 기능 검증 — PRD 4.4.

run_agent(max_iterations=1)로 딱 한 턴만 실행하고 강제로 멈춘 뒤(status='running'인 채로 남음 —
실제 프로세스가 중간에 죽은 것과 같은 상태), resume_run()이 그 지점부터 이어받아 끝까지
완료하는지 확인한다. 실제 OpenAI 호출을 두 번(중단 전 1턴 + 재개 후 나머지) 사용한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent_loop import run_agent, resume_run
import app.run_log_store as run_log_store
from app.insight_store import get_draft


def main():
    print("=== 1) 1턴만 실행하고 강제 중단 (크래시 시뮬레이션) ===")
    interrupted = run_agent("2026-03", "2026-03", max_iterations=1)
    print(f"  {interrupted}")

    run_id = interrupted["run_id"]
    run = run_log_store.get_run(run_id)
    assert run["status"] == "running", f"중단 직후엔 status가 running이어야 하는데 {run['status']}"
    assert run_log_store.load_messages(run_id) is not None, "재개용 대화 상태가 저장돼 있어야 함"
    print(f"  OK: status={run['status']}, 저장된 메시지 {len(run_log_store.load_messages(run_id))}개, "
          f"지금까지 재조회 {run['query_round_count']}회")

    print("\n=== 2) 같은 run_id로 재개 — 처음부터 다시 하지 않고 이어서 완료해야 함 ===")
    resumed = resume_run(run_id)
    print(f"  {resumed}")
    assert resumed["run_id"] == run_id, "재개는 같은 run_id를 유지해야 한다"
    assert resumed["status"] == "completed", f"재개 후 완료돼야 하는데 {resumed['status']}"
    assert resumed["wrote_draft"], "재개 후 인사이트 draft가 저장돼 있어야 한다"

    draft = get_draft(run_id)
    assert draft is not None
    print(f"  OK: 최종 status={resumed['status']}, 요약: {draft['summary_text'][:60]}...")

    print("\n=== 3) 이미 completed인 run은 재개할 수 없어야 함 ===")
    try:
        resume_run(run_id)
        print("  FAIL: 이미 끝난 run인데 재개가 허용됨")
    except ValueError as e:
        print(f"  OK: 예상대로 거부됨 — {e}")

    print("\n모든 재개 테스트 통과.")


if __name__ == "__main__":
    main()
