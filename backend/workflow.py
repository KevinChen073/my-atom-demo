from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .model import BudgetExceeded, ModelGateway, RunCancelled
from .exceptions import REASONS, classify, safe_phase
from .runner import LocalRunner, UnsafeSource
from .settings import Settings
from .store import Store, dumps


logger = logging.getLogger(__name__)


class RunState(TypedDict, total=False):
    run_id: str
    project_id: str
    request_text: str
    clarification: dict[str, Any]
    clarify_revision: int
    clarification_action: str
    answers: dict[str, str]
    plan: dict[str, Any]
    plan_feedback: str
    plan_action: str
    plan_revision: int
    spec_version: int
    card_id: str
    fix_rounds: int
    build_result: dict[str, Any]
    build_ok: bool
    version_id: str


def text_items(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:300] for item in value[:limit] if str(item).strip()]


def normalize_clarification(raw: dict[str, Any]) -> dict[str, Any]:
    questions = []
    for index, item in enumerate(raw.get("questions", [])[:3] if isinstance(raw.get("questions"), list) else []):
        if not isinstance(item, dict):
            continue
        question = str(item.get("text", "")).strip()[:250]
        if question:
            questions.append({"id": f"q{index + 1}", "text": question, "default": str(item.get("default", "")).strip()[:250], "required": bool(item.get("required", False))})
    return {"summary": str(raw.get("summary", "")).strip()[:1000], "assumptions": text_items(raw.get("assumptions"), 5), "questions": questions}


def normalize_plan(raw: dict[str, Any]) -> dict[str, Any]:
    pages = []
    for item in raw.get("pages", [])[:6] if isinstance(raw.get("pages"), list) else []:
        if isinstance(item, dict):
            pages.append({"name": str(item.get("name", "")).strip()[:100], "purpose": str(item.get("purpose", "")).strip()[:300]})
    entities = []
    for candidate in raw.get("entities", [])[:4] if isinstance(raw.get("entities"), list) else []:
        if not isinstance(candidate, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", str(candidate.get("name", ""))):
            continue
        fields = []
        for field in candidate.get("fields", [])[:12] if isinstance(candidate.get("fields"), list) else []:
            if not isinstance(field, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", str(field.get("name", ""))):
                continue
            if field["name"] in {"id", "created_at", "updated_at"} or field.get("type") not in {"text", "number", "boolean"}:
                continue
            fields.append({"name": field["name"], "type": field["type"], "required": bool(field.get("required", False))})
        if fields and candidate["name"] not in {entity["name"] for entity in entities}:
            entities.append({"name": candidate["name"], "fields": fields})
    plan = {
        "title": str(raw.get("title", "未命名应用")).strip()[:100],
        "pages": pages,
        "features": text_items(raw.get("features")),
        "data_model": text_items(raw.get("data_model")),
        "acceptance": text_items(raw.get("acceptance")),
        "tasks": text_items(raw.get("tasks")),
        "limitations": text_items(raw.get("limitations")),
        "entities": entities,
        "template": "React + TypeScript + Vite",
    }
    if not plan["features"] or not plan["acceptance"]:
        raise ValueError("模型计划缺少功能或验收点")
    implementation_text = " ".join(plan["features"] + plan["data_model"] + plan["acceptance"] + plan["tasks"] + [page["purpose"] for page in pages])
    if re.search(r"\b(?:localStorage|sessionStorage|indexedDB)\b", implementation_text, re.IGNORECASE):
        raise ValueError("计划包含不受控的浏览器存储；请使用服务端数据实体")
    return plan


class Workflow:
    def __init__(self, settings: Settings, store: Store, model: ModelGateway | Any = None):
        self.settings, self.store = settings, store
        self.model = model or ModelGateway(settings, store)
        self.runner = LocalRunner(settings, store)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_connection = sqlite3.connect(settings.checkpoint_db, check_same_thread=False)
        self.checkpointer = SqliteSaver(self.checkpoint_connection)
        self.graph = self._build_graph()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="myatom-worker")
        self.queued: set[str] = set()
        self.queue_lock = threading.Lock()

    def _build_graph(self):
        builder = StateGraph(RunState)
        for name, method in [
            ("clarify", self.clarify), ("wait_clarification", self.wait_clarification),
            ("plan", self.plan), ("wait_plan", self.wait_plan),
            ("prepare", self.prepare), ("code_loop", self.code_loop),
            ("build_test", self.build_test), ("diagnose", self.diagnose),
            ("package", self.package), ("needs_user", self.needs_user),
        ]:
            builder.add_node(name, method)
        builder.add_edge(START, "clarify")
        builder.add_edge("clarify", "wait_clarification")
        builder.add_conditional_edges("wait_clarification", lambda s: "clarify" if s.get("clarification_action") == "revise_clarification" else "plan", {"clarify": "clarify", "plan": "plan"})
        builder.add_edge("plan", "wait_plan")
        builder.add_conditional_edges("wait_plan", lambda s: "prepare" if s.get("plan_action") == "approve_plan" else "clarify" if s.get("plan_action") == "return_to_clarification" else "plan", {"prepare": "prepare", "plan": "plan", "clarify": "clarify"})
        builder.add_edge("prepare", "code_loop")
        builder.add_edge("code_loop", "build_test")
        builder.add_conditional_edges("build_test", self.route_build, {"package": "package", "diagnose": "diagnose", "needs_user": "needs_user"})
        builder.add_edge("diagnose", "code_loop")
        builder.add_edge("package", END)
        builder.add_edge("needs_user", END)
        return builder.compile(checkpointer=self.checkpointer)

    def clarify(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        self.store.update_run(run_id, status="clarifying", phase="Clarify", event_type="phase", event_payload={"phase": "Clarify"})
        raw = self.model.generate(
            run_id, "clarify", f"v{state.get('clarify_revision', 0)}",
            "你是 Web 产品需求分析师。分析需求，输出 JSON：summary 字符串、assumptions 字符串数组、questions 数组（最多三项，每项 text/default/required）。只问会影响实现的关键问题。",
            f"原始需求：{state['request_text']}\n固定模板：React + TypeScript + Vite。请给出可确认的需求澄清 JSON。",
            max_tokens=1400,
        )
        self._check_cancel(run_id)
        clarification = normalize_clarification(raw)
        card_id = str(uuid.uuid4())
        card = {"type": "clarification", "schema_version": 1, "card_id": card_id, "run_id": run_id, "status": "pending", "payload": clarification, "actions": ["confirm_clarification", "revise_clarification"]}
        version = state.get("spec_version", 0) + 1
        self.store.update_run(run_id, status="awaiting_clarification", phase="WaitClarify", card_json=dumps(card), card_id=card_id,
                              spec_version=version, event_type="card", event_payload={"card": card})
        return {"clarification": clarification, "card_id": card_id, "spec_version": version, "fix_rounds": 0}

    def wait_clarification(self, state: RunState) -> dict[str, Any]:
        decision = interrupt({"type": "clarification", "card_id": state["card_id"], "spec_version": state["spec_version"]})
        if decision.get("action") == "revise_clarification":
            return {"clarification_action": "revise_clarification", "request_text": decision["request_text"], "answers": {},
                    "clarify_revision": state.get("clarify_revision", 0) + 1, "plan_revision": state.get("plan_revision", 0) + 1}
        return {"clarification_action": "confirm_clarification", "answers": decision.get("answers", {})}

    def plan(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        revision = state.get("plan_revision", 0)
        self.store.update_run(run_id, status="planning", phase="Plan", event_type="phase", event_payload={"phase": "Plan", "revision": revision})
        system = ("你是 Web 应用架构师。输出 JSON：title、pages（name/purpose）、features、data_model、acceptance、tasks、limitations、entities。"
                  "数组成员除 pages、entities 外均为字符串。使用固定 React+TS+Vite 模板。"
                  "本轮提供本地交互预览与受控服务端数据 CRUD。禁止浏览器存储、外部 API 和自建后端。"
                  "需要跨刷新保存的数据在 entities 中列出，最多四个实体；每个实体有 name（英文小写下划线）和 fields 数组，"
                  "字段包含 name、type（text/number/boolean）、required。系统自动提供 id/created_at/updated_at。"
                  "例如待办实体 todos 字段 title:text 必填、completed:boolean 必填。计划须具体可测试。")
        prompt = (f"原始需求：{state['request_text']}\n澄清：{dumps(state['clarification'])}"
                  f"\n用户回答：{dumps(state.get('answers', {}))}\n计划修改意见：{state.get('plan_feedback', '')}"
                  "\n请输出完整 Build Plan JSON。")
        last_error: ValueError | None = None
        for correction in range(2):
            raw = self.model.generate(run_id, "plan", f"v{revision}-s{state['spec_version']}-c{correction}", system,
                                      prompt + (f"\n前版计划校验失败：{last_error}" if last_error else ""), max_tokens=2300)
            self._check_cancel(run_id)
            try:
                plan = normalize_plan(raw)
                break
            except ValueError as exc:
                last_error = exc
        else:
            raise RuntimeError(f"无法生成符合 MVP1 范围的计划：{last_error}")
        version = state["spec_version"] + 1
        card_id = str(uuid.uuid4())
        card = {"type": "build_plan", "schema_version": 1, "card_id": card_id, "run_id": run_id, "status": "pending", "payload": plan, "actions": ["approve_plan", "revise_plan", "return_to_clarification"]}
        self.store.update_run(run_id, status="awaiting_plan", phase="WaitPlan", card_json=dumps(card), card_id=card_id,
                              spec_version=version, plan_json=dumps(plan), event_type="card", event_payload={"card": card})
        return {"plan": plan, "card_id": card_id, "spec_version": version, "plan_feedback": "", "plan_action": ""}

    def wait_plan(self, state: RunState) -> dict[str, Any]:
        decision = interrupt({"type": "build_plan", "card_id": state["card_id"], "spec_version": state["spec_version"]})
        if decision.get("action") == "revise_plan":
            return {"plan_action": "revise_plan", "plan_feedback": str(decision.get("feedback", "")).strip()[:2000], "plan_revision": state.get("plan_revision", 0) + 1}
        if decision.get("action") == "return_to_clarification":
            return {"plan_action": "return_to_clarification", "clarify_revision": state.get("clarify_revision", 0) + 1,
                    "plan_revision": state.get("plan_revision", 0) + 1, "answers": {}}
        return {"plan_action": "approve_plan", "plan_feedback": ""}

    def prepare(self, state: RunState) -> dict[str, Any]:
        run = self.store.get_run(state["run_id"])
        if run["approved_spec_version"] != state["spec_version"]:
            raise RuntimeError("计划尚未确认，禁止写入生成文件")
        self.store.update_run(state["run_id"], status="building", phase="Prepare", event_type="phase", event_payload={"phase": "Prepare"})
        self.runner.prepare(state["project_id"], state["run_id"])
        return {}

    def code_loop(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        round_number = state.get("fix_rounds", 0)
        self.model.check_limits(run_id)
        self.store.update_run(run_id, status="building", phase="CodeLoop", fix_rounds=round_number,
                              event_type="phase", event_payload={"phase": "CodeLoop", "fix_round": round_number})
        base_system = (
            "你是 React+TypeScript 应用工程师。只输出 JSON 对象，字段 app_tsx 和 app_css 都是完整源码字符串。"
            "App.tsx 必须 export default 一个 React 组件，可使用 React hooks，只能 import 'react'、'./App.css' 和 './appData'。"
            "持久化数据必须 import { listRecords, createRecord, updateRecord, deleteRecord } from './appData' 按需调用；"
            "函数返回 Promise，列表在 useEffect 加载，操作成功后刷新列表，错误在页面上明确显示。实体名必须来自批准计划 entities。"
            "SDK 签名严格为 listRecords(entity)、createRecord(entity,data)、updateRecord(entity,id,data)、deleteRecord(entity,id)；"
            "记录 id 是字符串 UUID，传给更新/删除函数时直接使用。不要自己重新封装 SDK，也不要假设它接受不同参数。"
            "优先完整实现批准计划中的核心交互、状态变化和跨刷新持久化；只实现计划需要的数据操作，避免无关的复杂抽象。"
            "数据操作按记录 id 精确增删改；不要为单条变化重写或删除整个实体列表。"
            "不要在 React 的 setState 更新函数、渲染阶段或 effect 清理函数中调用异步 CRUD；在事件处理函数中等待操作成功，随后刷新列表并更新错误状态。"
            "若有高频计分和最高分保存，点击时只更新本轮分数；回合结束后用最终分数结算并写入最高分一次，避免快速连续点击时丢失更新。"
            "涉及提交的按钮在请求期间禁用，并使用同步的 in-flight 标记防止连续点击重复提交。"
            "输出前检查 TypeScript 未使用变量、状态引用及组件卸载清理，确保 tsc 严格构建通过。"
            "不得直接调用 fetch、外部 URL、浏览器存储、环境变量、动态 import、eval 或第三方组件。"
            "不要生成 package.json 或其他文件。制作与批准计划对应、能实际点击操作的单页应用。"
        )
        prompt = f"批准计划：{dumps(state['plan'])}\n原始需求：{state['request_text']}\n用户回答：{dumps(state.get('answers', {}))}"
        if state.get("build_result") and not state["build_result"].get("ok", True):
            prompt += f"\n上次构建错误：{state['build_result']['diagnostics'][-3500:]}\n请修复类型/构建错误并输出两个完整文件。"
        last_error: Exception | None = None
        for correction in range(2):
            raw = self.model.generate(run_id, "code_loop", f"r{round_number}-c{correction}", base_system,
                                      prompt + (f"\n前次源码校验失败：{last_error}" if last_error else ""), max_tokens=12000)
            self._check_cancel(run_id)
            try:
                files = {"src/App.tsx": raw["app_tsx"], "src/App.css": raw["app_css"]}
                written = self.runner.write_generated(state["project_id"], run_id, files, round_number)
                return {"written_files": written}
            except (KeyError, UnsafeSource) as exc:
                last_error = exc
        raise RuntimeError(f"生成源码未通过安全校验：{last_error}")

    def build_test(self, state: RunState) -> dict[str, Any]:
        if self.store.get_run(state["run_id"])["cancel_requested"]:
            raise RunCancelled("任务已取消")
        self.store.update_run(state["run_id"], phase="BuildTest", event_type="phase", event_payload={"phase": "BuildTest"})
        result = self.runner.build(state["project_id"], state["run_id"])
        self._check_cancel(state["run_id"])
        self.store.update_run(state["run_id"], event_type="build_result", event_payload={"ok": result["ok"], "steps": result["steps"], "diagnostics": result["diagnostics"][-1000:]})
        return {"build_result": result, "build_ok": result["ok"]}

    def route_build(self, state: RunState) -> str:
        if state["build_ok"]:
            return "package"
        return "diagnose" if state.get("fix_rounds", 0) < self.settings.max_fix_rounds else "needs_user"

    def diagnose(self, state: RunState) -> dict[str, Any]:
        next_round = state.get("fix_rounds", 0) + 1
        self.store.update_run(state["run_id"], phase="Diagnose", fix_rounds=next_round,
                              event_type="phase", event_payload={"phase": "Diagnose", "fix_round": next_round})
        return {"fix_rounds": next_round}

    def package(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        self._check_cancel(run_id)
        self.store.update_run(run_id, phase="Package", event_type="phase", event_payload={"phase": "Package"})
        manifest = self.runner.package(state["project_id"], run_id, state["build_result"])
        manifest["entities"] = state["plan"].get("entities", [])
        self._check_cancel(run_id)
        version = self.store.save_version(state["project_id"], run_id, manifest)
        self.store.update_run(run_id, status="completed", phase="Done", version_id=version["id"], card_json=dumps({
            "type": "test_result", "schema_version": 1, "card_id": str(uuid.uuid4()), "run_id": run_id,
            "status": "passed", "payload": {"version_id": version["id"], "build": manifest["build"], "files": manifest["files"],
            "diagnostics_ref": f"/api/runs/{run_id}/build-log", "browser_check": "not_run"}, "actions": []
        }), event_type="completed", event_payload={"version_id": version["id"]})
        return {"version_id": version["id"]}

    def needs_user(self, state: RunState) -> dict[str, Any]:
        error = state["build_result"]["diagnostics"][-2000:]
        card = self._failure_card(state["run_id"], error, state["build_result"].get("steps", []))
        self.store.update_run(state["run_id"], status="failed", phase="NeedsUser", error=error, card_json=dumps(card),
                              event_type="failed", event_payload={"reason": "build_failed", "fix_rounds": state.get("fix_rounds", 0)})
        self._capture_failure(state["run_id"], source="build", phase="BuildTest",
                              code="build_failed", exception_type="BuildFailure")
        return {}

    def _capture_failure(self, run_id: str, *, source: str, phase: str,
                         code: str, exception_type: str) -> None:
        try:
            run = self.store.get_run(run_id)
            self.store.record_exception(trace_id=run["trace_id"], project_id=run["project_id"],
                                        run_id=run_id, source=source, phase=safe_phase(phase),
                                        code=code, exception_type=exception_type)
        except Exception:
            # Telemetry must not change the run outcome or expose the failing payload.
            logger.warning("Exception metadata capture failed for terminal run")

    def _check_cancel(self, run_id: str) -> None:
        if self.store.get_run(run_id)["cancel_requested"]:
            raise RunCancelled("任务已取消")

    @staticmethod
    def _failure_card(run_id: str, error: str, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {"type": "test_result", "schema_version": 1, "card_id": str(uuid.uuid4()), "run_id": run_id,
                "status": "failed", "payload": {"build": {"ok": False, "steps": steps or []},
                "diagnostics": error[-2000:], "diagnostics_ref": f"/api/runs/{run_id}/build-log" if steps else None,
                "browser_check": "not_run_mvp1"}, "actions": []}

    def enqueue(self, run_id: str) -> None:
        with self.queue_lock:
            if run_id in self.queued:
                return
            self.queued.add(run_id)
        self.executor.submit(self._process, run_id)

    def _process(self, run_id: str) -> None:
        try:
            run = self.store.get_run(run_id)
            if run["status"] not in {"clarifying", "planning", "building"}:
                return
            config = {"configurable": {"thread_id": run_id}}
            pending = self.store.pending_decision(run_id)
            snapshot = self.graph.get_state(config)
            if pending and snapshot.next and snapshot.next[0] in {"wait_clarification", "wait_plan"}:
                decision_input = {"action": pending["action"], **(pending["payload"] or {})}
                self.graph.invoke(Command(resume=decision_input), config=config)
                self.store.mark_decision_processed(pending["id"])
            elif snapshot.next:
                self.graph.invoke(None, config=config)
            elif not snapshot.values:
                self.graph.invoke({"run_id": run_id, "project_id": run["project_id"], "request_text": run["request_text"]}, config=config)
            elif pending:
                self.store.mark_decision_processed(pending["id"])
        except RunCancelled as exc:
            self.store.update_run(run_id, status="cancelled", phase="Cancelled", error=str(exc), event_type="cancelled", event_payload={})
        except BudgetExceeded as exc:
            previous_phase = self.store.get_run(run_id)["phase"]
            reason = REASONS["budget_exceeded"]
            self.store.update_run(run_id, status="budget_exceeded", phase="NeedsUser", error=reason,
                                  card_json=dumps(self._failure_card(run_id, reason)),
                                  event_type="budget_exceeded", event_payload={"reason": "budget_exceeded"})
            self._capture_failure(run_id, source="agent", phase=previous_phase,
                                  code="budget_exceeded", exception_type="BudgetExceeded")
        except Exception as exc:
            previous_phase = self.store.get_run(run_id)["phase"]
            code, kind = classify(exc)
            reason = REASONS[code]
            self.store.update_run(run_id, status="failed", phase="NeedsUser", error=reason,
                                  card_json=dumps(self._failure_card(run_id, reason)),
                                  event_type="failed", event_payload={"reason": code})
            self._capture_failure(run_id, source="agent", phase=previous_phase,
                                  code=code, exception_type=kind)
        finally:
            with self.queue_lock:
                self.queued.discard(run_id)
            # A decision may arrive after this worker entered the waiting node but
            # before it left the queue. In that case the API's enqueue was skipped.
            run = self.store.get_run(run_id)
            if run["status"] in {"clarifying", "planning", "building"} and self.store.pending_decision(run_id):
                self.enqueue(run_id)

    def recover(self) -> None:
        for run in self.store.get_recoverable_runs():
            self.enqueue(run["id"])
