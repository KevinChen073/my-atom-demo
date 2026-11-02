"""Opt-in, paid-model smoke for the example catalog.

Run from the repository root: .venv/Scripts/python -m tests.live_examples_smoke --id pomodoro_todo
Each invocation creates an isolated local project and records only diagnostics,
not model prompts, source code, or credentials.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.preview import create_preview_app
from backend.settings import ROOT, Settings


TERMINAL = {"failed", "cancelled", "budget_exceeded"}
PLAN_TERMS = {
    "pomodoro_todo": [("待办", "任务"), ("番茄", "计时"), ("暂停",)],
    "elder_clicker": [("点击",), ("皮肤", "造型"), ("分数", "计分")],
    "mobile_ordering": [("商品", "菜单"), ("购物车",), ("订单", "下单")],
}


def wait_for(client: TestClient, run_id: str, expected: str, deadline: float, *, after_spec: int = -1) -> dict:
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        if (run["status"] == expected and run["spec_version"] > after_spec) or run["status"] in TERMINAL:
            return run
        if expected == "awaiting_plan" and run["status"] == "awaiting_clarification" and run["spec_version"] > after_spec:
            return run
        time.sleep(0.5)
    raise TimeoutError(f"run {run_id} did not reach {expected}")


def plan_gaps(example_id: str, plan: dict) -> list[str]:
    gaps: list[str] = []
    wording = " ".join(str(part) for key in ("features", "data_model", "acceptance", "tasks") for part in plan.get(key, []))
    if "localStorage" not in wording:
        gaps.append("缺少预览域 localStorage 持久化说明")
    for alternatives in PLAN_TERMS.get(example_id, []):
        if not any(term in wording for term in alternatives):
            gaps.append("缺少关键功能：" + "/".join(alternatives))
    if example_id == "pomodoro_todo" and "番茄数" not in wording:
        gaps.append("任务数据缺少番茄数")
    if example_id == "elder_clicker":
        if "最高分" not in wording or "皮肤" not in wording:
            gaps.append("本地数据缺少最高分或选中皮肤")
        high_score_lines = [str(item) for key in ("features", "acceptance", "tasks") for item in plan.get(key, [])
                            if "演示" in str(item) and "最高分" in str(item)]
        if not any(("计入" in line or "更新" in line or "保存" in line) and "不计入" not in line for line in high_score_lines):
            gaps.append("10 秒演示回合也必须计入统一最高分")
        if any("演示" in str(item) and "不计入" in str(item) for item in plan.get("limitations", [])):
            gaps.append("计划与演示回合最高分要求冲突")
        if not any(("回合结束" in line or "结束时" in line) and "最高分" in line for line in high_score_lines +
                   [str(item) for key in ("features", "acceptance", "tasks") for item in plan.get(key, [])]):
            gaps.append("回合结束按最终本轮得分结算最高分，避免快速连点漏分")
    if example_id == "mobile_ordering" and "订单" not in wording:
        gaps.append("缺少本地订单历史")
    return gaps


def submit_decision(client: TestClient, run: dict, action: str, **extra: object) -> None:
    response = client.post(
        f"/api/runs/{run['id']}/decisions",
        json={"card_id": run["card_id"], "spec_version": run["spec_version"], "action": action, **extra},
    )
    response.raise_for_status()


def version_hooks_use_local_storage(client: TestClient, version: dict) -> bool:
    hook_paths = [item["path"] for item in version["manifest"]["files"]
                  if item["path"].startswith("src/hooks/") and item["path"].endswith(".ts")]
    sources = []
    for hook_path in hook_paths:
        response = client.get(f"/api/versions/{version['id']}/files/{hook_path}")
        response.raise_for_status()
        sources.append(response.text)
    return any("localStorage" in source for source in sources)


def run_example(example: dict, settings: Settings, timeout: int) -> dict:
    started = time.monotonic()
    result: dict = {"example_id": example["id"], "status": "not_started", "browser_check": "not_run"}
    deadline = started + timeout
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/projects", json={"title": "冒烟：" + example["title"]})
        response.raise_for_status()
        project_id = response.json()["id"]
        response = client.post(
            f"/api/projects/{project_id}/runs",
            json={"request_text": example["request_text"]},
            headers={"X-Myatom-Model-Config": json.dumps({
                "provider": "deepseek" if "api.deepseek.com" in settings.model_base_url else "openai_compatible",
                "api_key": settings.model_api_key, "base_url": settings.model_base_url,
                "model_name": settings.model_name})},
        )
        response.raise_for_status()
        run_id = response.json()["run"]["id"]
        result.update(project_id=project_id, run_id=run_id)
        try:
            run = wait_for(client, run_id, "awaiting_clarification", deadline)
            if run["status"] != "awaiting_clarification":
                raise RuntimeError(run.get("error") or run["status"])
            questions = run["card"]["payload"]["questions"]
            answers = {item["id"]: item["default"] or "按原始需求实现" for item in questions}
            submit_decision(client, run, "confirm_clarification", answers=answers)
            run = wait_for(client, run_id, "awaiting_plan", deadline, after_spec=run["spec_version"])
            while run["status"] == "awaiting_clarification":
                questions = run["card"]["payload"]["questions"]
                answers = {item["id"]: item["default"] or "按原始需求实现" for item in questions}
                submit_decision(client, run, "confirm_clarification", answers=answers)
                run = wait_for(client, run_id, "awaiting_plan", deadline, after_spec=run["spec_version"])
            if run["status"] != "awaiting_plan":
                raise RuntimeError(run.get("error") or run["status"])
            gaps = plan_gaps(example["id"], run["plan"])
            if gaps:
                old_spec = run["spec_version"]
                submit_decision(client, run, "revise_plan", feedback="请补足以下验收项，勿改动原需求：" + "；".join(gaps))
                run = wait_for(client, run_id, "awaiting_plan", deadline, after_spec=old_spec)
                if run["status"] != "awaiting_plan":
                    raise RuntimeError(run.get("error") or run["status"])
                gaps = plan_gaps(example["id"], run["plan"])
            result["plan_gaps"] = gaps
            if gaps:
                result["status"] = "plan_rejected"
                return result
            submit_decision(client, run, "approve_plan")
            run = wait_for(client, run_id, "completed", deadline)
            result.update(
                status=run["status"],
                model_calls=run["model_calls"],
                tokens_used=run["tokens_used"],
                fix_rounds=run["fix_rounds"],
            )
            if run["status"] != "completed":
                result["error"] = run.get("error")
                return result
            version = client.get(f"/api/projects/{project_id}").json()["versions"][0]
            result["version_id"] = version["id"]
            result["build_ok"] = version["manifest"]["build"]["ok"]
            result["uses_local_storage"] = version_hooks_use_local_storage(client, version)
            if example["smoke"]["requires_local_storage"] and not result["uses_local_storage"]:
                result["status"] = "contract_failed"
                return result
            issued = client.get(f"/api/versions/{version['id']}/preview")
            issued.raise_for_status()
            path = urlsplit(issued.json()["url"])
            with TestClient(create_preview_app(settings), base_url=f"{path.scheme}://{path.netloc}") as preview:
                opened = preview.get(path.path + "?" + path.query)
                result["preview_http"] = opened.status_code
                result["preview_has_assets"] = "assets" in opened.text
                result["origin"] = path.hostname
            if not result["build_ok"] or result["preview_http"] != 200 or not result["preview_has_assets"]:
                result["status"] = "contract_failed"
            return result
        except Exception as exc:
            result["status"] = "script_error"
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result
        finally:
            result["elapsed_seconds"] = round(time.monotonic() - started, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="catalog example id; one paid run per invocation")
    parser.add_argument("--timeout", type=int, default=900)
    arguments = parser.parse_args()
    catalog = json.loads((ROOT / "examples" / "catalog.json").read_text(encoding="utf-8"))
    example = next((item for item in catalog["examples"] if item["id"] == arguments.id), None)
    if example is None:
        parser.error("unknown example id")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    settings = Settings(data_dir=ROOT / "data" / "live-examples" / f"{timestamp}-{arguments.id}")
    if not settings.model_api_key:
        parser.error("MODEL_API_KEY is missing from .env")
    result = run_example(example, settings, arguments.timeout)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
