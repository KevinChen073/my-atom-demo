from __future__ import annotations

import json
import hashlib
import logging
import math
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

from .build_harness import build_repair_feedback, error_fingerprints, repair_stop_reason
from .budget import EXTENSION_STEPS, effective_limits
from .model import BudgetExceeded, ModelGateway, ModelOutputError, RunCancelled
from .exceptions import (MODEL_OUTPUT_REASONS, PLAN_VALIDATION_REASONS, PlanValidationError, REASONS,
                         SourceValidationError, cause_chain, classify, plan_validation_error_code, safe_phase)
from .runner import LocalRunner
from .settings import Settings
from .source_harness import (GENERATED_FILE, TEMPLATE_STORAGE_FILE, repair_feedback, source_contract_prompt,
                             source_signatures, source_validation_reason, SOURCE_FAILURE_REASONS,
                             repair_interface_context)
from .store import Store, dumps


logger = logging.getLogger(__name__)


class RunState(TypedDict, total=False):
    run_id: str
    project_id: str
    request_text: str
    clarification: dict[str, Any]
    clarify_revision: int
    clarification_action: str
    clarification_card_count: int
    clarification_history: list[dict[str, Any]]
    asked_question_keys: list[str]
    open_gaps: list[str]
    clarity_complete: bool
    stop_reason: str
    answers: dict[str, str]
    plan: dict[str, Any]
    plan_feedback: str
    plan_action: str
    plan_revision: int
    spec_version: int
    card_id: str
    fix_rounds: int
    build_failure_history: list[list[str]]
    repair_failure_history: list[list[str]]
    build_stop_code: str
    source_stop_code: str
    source_ok: bool
    source_feedback: dict[str, Any]
    code_feedback: dict[str, Any]
    source_candidate_ref: str
    model_output_key: str
    model_output_mode: str
    model_output_targets: list[str]
    candidate_number: int
    repair_waiting: bool
    manual_rounds: int
    repair_action: str
    repair_instruction: str
    build_result: dict[str, Any]
    build_ok: bool
    diagnosis: dict[str, Any]
    candidate: dict[str, Any]
    preview_ok: bool
    preview_result: dict[str, Any]
    version_id: str


def text_items(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:300] for item in value[:limit] if str(item).strip()]


def normalize_clarification(raw: dict[str, Any]) -> dict[str, Any]:
    source = raw.get("questions")
    if not isinstance(source, list) or not 1 <= len(source) <= 3:
        raise ValueError("每轮澄清必须提出 1–3 个问题")
    questions = []
    for index, item in enumerate(source):
        if not isinstance(item, dict):
            raise ValueError("澄清问题格式无效")
        question = str(item.get("text", "")).strip()[:250]
        if not question:
            raise ValueError("澄清问题不能为空")
        questions.append({"id": f"q{index + 1}", "text": question, "default": str(item.get("default", "")).strip()[:250], "required": bool(item.get("required", False))})
    return {"summary": str(raw.get("summary", "")).strip()[:1000], "assumptions": text_items(raw.get("assumptions"), 5), "questions": questions}


def question_key(value: str) -> str:
    return re.sub(r"[^\w]", "", value).casefold()


def classify_build_failure(result: dict[str, Any], run_id: str) -> dict[str, Any]:
    if result.get("ok"):
        return {"category": "passed", "command": "", "evidence_ref": f"/api/runs/{run_id}/build-log", "repairable": False}
    step = (result.get("steps") or [{}])[-1]
    command = str(step.get("command", ""))
    output = str(result.get("diagnostics", ""))
    if result.get("environment_failure"):
        category, repairable, reason = "environment_failure", False, output[:300] or "构建环境执行失败"
    elif command.startswith("npm ci"):
        category, repairable, reason = "dependency_install", False, "依赖安装失败，重新生成应用源码无法修复此环境问题"
    elif command.startswith("npm run build") and re.search(r"error TS\d+|Could not resolve|Failed to resolve import|Transform failed|Unexpected token|error during build", output, re.I):
        category, repairable, reason = "source_compile", True, "生成源码未通过类型或打包检查"
    else:
        category, repairable, reason = "build_unknown", False, "构建失败原因未归类，已停止自动改写源码"
    return {"category": category, "command": command, "evidence_ref": f"/api/runs/{run_id}/build-log",
            "repairable": repairable, "reason": reason, "exit_code": step.get("exit_code")}


def build_failure_summary(events: list[dict[str, Any]], diagnosis: dict[str, Any], fix_rounds: int) -> dict[str, Any]:
    """Summarize actual build evidence without asking a model to guess a cause."""
    attempts = []
    for event in events:
        if event["type"] != "build_result" or event["payload"].get("ok"):
            continue
        payload = event["payload"]
        lines = str(payload.get("diagnostics", "")).splitlines()
        errors = [line.strip()[:240] for line in lines if re.search(r"error TS\d+|Could not resolve|Failed to resolve import|Transform failed|Unexpected token", line, re.I)]
        step = (payload.get("steps") or [{}])[-1]
        attempts.append({"number": len(attempts) + 1, "command": step.get("command", ""),
                         "error": "; ".join(errors[:2])[:420] if errors else (lines[-1].strip()[:240] if lines else "构建命令失败")})
    if any("appData" in item["error"] for item in attempts):
        cause = "此前候选代码引用过模板中不存在的 appData；最近一次错误见下方。当前交付物只通过项目存储适配器保存业务数据。"
    elif diagnosis.get("category") == "source_compile":
        cause = "生成的 TypeScript 源码未通过编译；可在保留现有需求与计划的前提下修复。"
    elif diagnosis.get("category") in {"environment_failure", "dependency_install"}:
        cause = "构建环境或依赖安装失败；需要先排查环境，再决定是否重建。"
    else:
        cause = str(diagnosis.get("reason") or "构建失败，原因尚未归类。")[:240]
    return {"cause": cause, "latest_error": attempts[-1]["error"] if attempts else str(diagnosis.get("reason", "构建失败"))[:240],
            "attempts": attempts[-5:], "total_attempts": len(attempts), "automatic_repairs": fix_rounds,
            "command": diagnosis.get("command") or (attempts[-1]["command"] if attempts else ""),
            "evidence_ref": diagnosis.get("evidence_ref") or (f"/api/runs/{events[0]['run_id']}/build-log" if events else "")}


def source_failure_summary(events: list[dict[str, Any]], stop_reason: str, fix_rounds: int) -> dict[str, Any]:
    attempts = []
    for event in events:
        if event["type"] != "source_validation_failed":
            continue
        payload = event["payload"]
        if payload.get("issues"):
            descriptions = [
                (f"{issue['file']}：" if issue.get("file") else "") + str(issue.get("feedback") or SOURCE_FAILURE_REASONS["invalid_source"])[:240]
                for issue in payload["issues"][:3]
            ]
        else:
            descriptions = [SOURCE_FAILURE_REASONS.get(code, SOURCE_FAILURE_REASONS["invalid_source"])
                            for code in payload.get("reason_codes", [payload.get("reason_code")])]
        attempts.append({"number": len(attempts) + 1, "command": "源码校验",
                         "error": "；".join(descriptions[:3])})
    return {"stage": "source_validation", "cause": stop_reason or "生成源码未通过规则校验。",
            "latest_error": attempts[-1]["error"] if attempts else "源码校验未通过",
            "attempts": attempts[-5:], "total_attempts": len(attempts),
            "automatic_repairs": fix_rounds, "command": "源码校验", "evidence_ref": ""}


def normalize_plan(raw: dict[str, Any]) -> dict[str, Any]:
    def plan_items(name: str, limit: int) -> list[str]:
        source = raw.get(name)
        if isinstance(source, list) and len(source) > limit:
            raise ValueError(f"计划中的 {name} 超过 {limit} 项，不能静默截断已确认要求")
        return text_items(source, limit)
    page_source = raw.get("pages", [])
    if isinstance(page_source, list) and len(page_source) > 6:
        raise ValueError("计划页面超过 6 个，不能静默截断")
    pages = []
    for item in page_source if isinstance(page_source, list) else []:
        if isinstance(item, dict):
            pages.append({"name": str(item.get("name", "")).strip()[:100], "purpose": str(item.get("purpose", "")).strip()[:300]})
    plan = {
        "title": str(raw.get("title", "未命名应用")).strip()[:100],
        "pages": pages,
        "features": plan_items("features", 32),
        "data_model": plan_items("data_model", 32),
        "acceptance": plan_items("acceptance", 48),
        "tasks": plan_items("tasks", 32),
        "limitations": plan_items("limitations", 32),
        "entities": [],
        "template": "React + TypeScript + Vite",
    }
    if not plan["features"] or not plan["acceptance"]:
        raise ValueError("模型计划缺少功能或验收点")
    storage = re.compile(r"(?:服务端数据|服务端保存|服务端存储|服务端读写|服务端持久|服务器数据|服务器存储|数据库|\bappData\b|\b(?:SQL|SQLite|IndexedDB|sessionStorage)\b)", re.IGNORECASE)
    negation = re.compile(r"(?:禁止|不得|不使用|不用|避免|不要|不采用|无需|不能|不应|未使用|不提供|不涉及|不支持|不允许|不接|不依赖|没有|不含|无|without|avoid|do not|don't).{0,20}$", re.IGNORECASE)
    plan_text = ([plan["title"]] + plan["features"] + plan["data_model"] + plan["acceptance"]
                 + plan["tasks"] + plan["limitations"] + [part for page in pages for part in page.values()])
    for item in plan_text:
        for clause in re.split(r"[，,。；;\n]", item):
            for match in storage.finditer(clause):
                if not negation.search(clause[:match.start()].rstrip()):
                    raise ValueError("生成应用只能通过项目存储适配器在 localStorage 保存业务数据")
    return plan


def merge_iteration_plan(raw: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    """Keep the approved baseline unless the plan card explicitly names a change."""
    previous = normalize_plan(base["plan"])
    delta = normalize_plan({**raw, "features": raw.get("features") or previous["features"],
                            "acceptance": raw.get("acceptance") or previous["acceptance"]})
    if isinstance(raw.get("removed_features"), list) and len(raw["removed_features"]) > 32:
        raise ValueError("删除功能列表超过当前计划容量")
    removed = text_items(raw.get("removed_features"), 32)
    modified = raw.get("modified_features") or {}
    if not isinstance(modified, dict) or any(not isinstance(key, str) or not isinstance(value, str) or not value.strip()
                                               for key, value in modified.items()):
        raise ValueError("功能修改列表格式无效")
    if any(item not in previous["features"] for item in removed + list(modified)) or set(removed) & set(modified):
        raise ValueError("待删除或修改的功能必须准确引用上一版功能")
    retained = [item for item in previous["features"] if item not in removed and item not in modified]
    changed = [modified[item].strip()[:300] for item in previous["features"] if item in modified]
    added = [item for item in delta["features"] if item not in previous["features"] and item not in changed]
    def unique(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))
    delta["features"] = unique(retained + changed + added)
    for key in ("data_model", "acceptance", "tasks", "limitations"):
        delta[key] = unique(previous[key] + delta[key])
    if len(delta["features"]) > 32 or len(delta["acceptance"]) > 48 or any(len(delta[key]) > 32 for key in ("data_model", "tasks", "limitations")):
        raise ValueError("累计需求超过当前单应用计划容量，请缩减本轮范围")
    delta["pages"] = previous["pages"] + [page for page in delta["pages"] if page not in previous["pages"]]
    if len(delta["pages"]) > 6:
        raise ValueError("累计页面超过 6 个，请缩减本轮范围")
    changed_files = raw.get("changed_files") or []
    new_files = raw.get("new_files") or []
    if not isinstance(changed_files, list) or not isinstance(new_files, list):
        raise ValueError("修改文件列表格式无效")
    paths = changed_files + new_files
    if any(not isinstance(path, str) or not GENERATED_FILE.fullmatch(path) for path in paths):
        raise ValueError("修改文件超出固定模板")
    delta["change_set"] = {"retained": retained, "modified": [{"before": key, "after": modified[key]} for key in modified],
                           "removed": removed, "added": added}
    delta["changed_files"] = sorted(set(changed_files))
    delta["new_files"] = sorted(set(new_files))
    return delta


class Workflow:
    def __init__(self, settings: Settings, store: Store, model: ModelGateway | Any = None):
        self.settings, self.store = settings, store
        self.model = model or ModelGateway(settings, store)
        self.runner = LocalRunner(settings, store)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        if settings.azure_sql_connection_string:
            from .azure_sql_checkpoint import AzureSqlSaver
            self.checkpointer = AzureSqlSaver(settings.azure_sql_connection_string)
            self.checkpoint_connection = self.checkpointer
        elif settings.database_url:
            import psycopg
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres import PostgresSaver
            self.checkpoint_connection = psycopg.connect(settings.database_url, autocommit=True,
                                                         row_factory=dict_row, connect_timeout=5)
            self.checkpointer = PostgresSaver(self.checkpoint_connection)
        else:
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
            ("clarity_gate", self.clarity_gate),
            ("plan", self.plan), ("wait_plan", self.wait_plan),
            ("prepare", self.prepare), ("code_loop", self.code_loop), ("validate_source", self.validate_source),
            ("build_test", self.build_test), ("diagnose", self.diagnose),
            ("package_candidate", self.package_candidate), ("preview_check", self.preview_check),
            ("commit_version", self.commit_version), ("needs_user", self.needs_user),
            ("wait_repair", self.wait_repair),
        ]:
            builder.add_node(name, method)
        builder.add_edge(START, "clarify")
        builder.add_edge("clarify", "wait_clarification")
        builder.add_conditional_edges("wait_clarification", self.route_clarification, {"clarify": "clarify", "clarity_gate": "clarity_gate", "needs_user": "needs_user"})
        builder.add_conditional_edges("clarity_gate", self.route_clarity, {"clarify": "clarify", "plan": "plan", "needs_user": "needs_user"})
        builder.add_edge("plan", "wait_plan")
        builder.add_conditional_edges("wait_plan", lambda s: "prepare" if s.get("plan_action") == "approve_plan" else "plan", {"prepare": "prepare", "plan": "plan"})
        builder.add_edge("prepare", "code_loop")
        builder.add_edge("code_loop", "validate_source")
        builder.add_conditional_edges("validate_source", self.route_source, {"code_loop": "code_loop", "build_test": "build_test", "needs_user": "needs_user"})
        builder.add_conditional_edges("build_test", self.route_build, {"package_candidate": "package_candidate", "diagnose": "diagnose", "needs_user": "needs_user"})
        builder.add_edge("diagnose", "code_loop")
        builder.add_edge("package_candidate", "preview_check")
        builder.add_conditional_edges("preview_check", lambda s: "commit_version" if s.get("preview_ok") else "needs_user", {"commit_version": "commit_version", "needs_user": "needs_user"})
        builder.add_edge("commit_version", END)
        builder.add_conditional_edges("needs_user", lambda s: "wait_repair" if s.get("repair_waiting", bool(s.get("build_result") and not s["build_result"].get("ok"))) else END,
                                      {"wait_repair": "wait_repair", END: END})
        builder.add_conditional_edges("wait_repair", lambda s: "build_test" if s.get("repair_action") == "rebuild" else "code_loop",
                                      {"build_test": "build_test", "code_loop": "code_loop"})
        return builder.compile(checkpointer=self.checkpointer)

    def clarify(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        count = state.get("clarification_card_count", 0)
        if count >= 3:
            raise RuntimeError("澄清轮次已达上限")
        self.store.update_run(run_id, status="clarifying", phase="Clarify", event_type="phase", event_payload={"phase": "Clarify"})
        history = state.get("clarification_history", [])
        seen = set(state.get("asked_question_keys", []))
        last_error: ValueError | None = None
        for correction in range(2):
            raw = self.model.generate(
                run_id, "clarify", f"card{count + 1}-rev{state.get('clarify_revision', 0)}-c{correction}",
                "你是 Web 产品需求分析师。输出 JSON：summary 字符串、assumptions 字符串数组、questions 数组，每轮必须 1–3 项，每项 text/default/required。只问影响实现且未回答的关键问题，不重复原需求长摘要。固定 React+TypeScript+Vite；业务数据只通过项目存储适配器在工作台共享 origin 的 localStorage 中保存，不提供服务端业务 CRUD。",
                f"原始需求：{state['request_text']}\n过往问答：{dumps(history)}\n尚缺信息：{dumps(state.get('open_gaps', []))}"
                + (f"\n上一可用版本的已确认功能：{dumps(self.store.get_run(run_id).get('base_spec', {}).get('plan', {}).get('features', []))}。只澄清本轮变化。" if self.store.get_run(run_id).get('base_version_id') else "")
                + (f"\n上次问题校验失败：{last_error}" if last_error else "") + "\n请给出本轮澄清 JSON。",
                max_tokens=1400,
            )
            self._check_cancel(run_id)
            try:
                clarification = normalize_clarification(raw)
                keys = [question_key(item["text"]) for item in clarification["questions"]]
                if len(set(keys)) != len(keys) or set(keys) & seen:
                    raise ValueError("澄清问题与已有问题重复")
                break
            except ValueError as exc:
                last_error = exc
        else:
            raise RuntimeError(f"澄清卡校验失败：{last_error}")
        card_id = str(uuid.uuid4())
        card = {"type": "clarification", "schema_version": 1, "card_id": card_id, "run_id": run_id, "status": "pending", "payload": clarification, "actions": ["confirm_clarification", "revise_clarification"]}
        version = state.get("spec_version", 0) + 1
        self.store.update_run(run_id, status="awaiting_clarification", phase="WaitClarify", card_json=dumps(card), card_id=card_id,
                              spec_version=version, event_type="card", event_payload={"card": card})
        return {"clarification": clarification, "card_id": card_id, "spec_version": version,
                "clarification_card_count": count + 1, "asked_question_keys": sorted(seen | set(keys)), "fix_rounds": 0}

    def wait_clarification(self, state: RunState) -> dict[str, Any]:
        decision = interrupt({"type": "clarification", "card_id": state["card_id"], "spec_version": state["spec_version"]})
        if decision.get("action") == "revise_clarification":
            return {"clarification_action": "revise_clarification", "request_text": decision["request_text"], "answers": {},
                    "clarification_history": [], "open_gaps": [],
                    "stop_reason": "本轮已完成 3 张澄清卡。请以更新后的需求开始新一轮。" if state.get("clarification_card_count", 0) >= 3 else "",
                    "clarify_revision": state.get("clarify_revision", 0) + 1, "plan_revision": state.get("plan_revision", 0) + 1}
        answers = decision.get("answers", {})
        history = state.get("clarification_history", []) + [
            {"question": question["text"], "answer": answers.get(question["id"], ""), "card_id": state["card_id"]}
            for question in state["clarification"]["questions"]
        ]
        return {"clarification_action": "confirm_clarification", "answers": answers, "clarification_history": history}

    @staticmethod
    def route_clarification(state: RunState) -> str:
        if state.get("clarification_action") == "revise_clarification":
            return "clarify" if state.get("clarification_card_count", 0) < 3 else "needs_user"
        return "clarity_gate"

    def clarity_gate(self, state: RunState) -> dict[str, Any]:
        self.store.update_run(state["run_id"], status="clarifying", phase="ClarityGate", event_type="phase", event_payload={"phase": "ClarityGate"})
        raw = self.model.generate(
            state["run_id"], "clarity_gate", f"card{state['clarification_card_count']}-rev{state.get('clarify_revision', 0)}",
            "判断已确认的需求是否足够生成固定 React+TypeScript+Vite 应用。只输出 JSON：complete 布尔值、missing 字符串数组。不要因非关键细节继续追问；如缺少影响实现的约束，complete=false。业务存储只允许通过项目存储适配器使用共享 origin 的 localStorage。",
            f"需求：{state['request_text']}\n上一可用版本：{dumps(self.store.get_run(state['run_id']).get('base_spec'))}\n已确认问答：{dumps(state.get('clarification_history', []))}\n请判断是否完整。",
            max_tokens=600,
        )
        if not isinstance(raw.get("complete"), bool):
            raise RuntimeError("澄清完整性判定格式无效")
        missing = text_items(raw.get("missing"), 3)
        if not raw["complete"] and not missing:
            missing = ["关键实现约束仍未明确"]
        confirmed = [
            {"question": str(item.get("question", ""))[:100], "answer": str(item.get("answer", ""))[:120]}
            for item in state.get("clarification_history", [])[-len(state["clarification"]["questions"]):]
            if isinstance(item, dict)
        ]
        self.store.update_run(state["run_id"], event_type="clarity_result", event_payload={
            "round": state["clarification_card_count"], "confirmed": confirmed,
            "complete": raw["complete"], "missing": missing,
        })
        return {"clarity_complete": raw["complete"], "open_gaps": missing,
                "stop_reason": "澄清三轮后仍缺少关键约束：" + "；".join(missing) if not raw["complete"] and state["clarification_card_count"] >= 3 else ""}

    @staticmethod
    def route_clarity(state: RunState) -> str:
        if state.get("clarity_complete"):
            return "plan"
        return "clarify" if state.get("clarification_card_count", 0) < 3 else "needs_user"

    def plan(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        run = self.store.get_run(run_id)
        base_spec = run.get("base_spec") if run.get("base_version_id") else None
        revision = state.get("plan_revision", 0)
        self.store.update_run(run_id, status="planning", phase="Plan", event_type="phase", event_payload={"phase": "Plan", "revision": revision})
        request_clauses = re.split(r"[，,。；;\n]", state["request_text"])
        legacy_storage = re.compile(r"\bappData\b|(?:服务端|服务器).{0,10}(?:存储|保存|数据接口|读写)", re.IGNORECASE)
        negation = re.compile(r"(?:禁止|不得|不使用|不用|避免|不要|不采用|无需|不能|不应|未使用|不提供|不涉及|不支持|不允许|不接|不依赖).{0,20}$")
        incompatible_request = any(
            re.search(r"(?:不使用|不用|禁止).{0,10}(?:浏览器存储|localStorage)", clause, re.IGNORECASE)
            or any(not negation.search(clause[:match.start()].rstrip()) for match in legacy_storage.finditer(clause))
            for clause in request_clauses
        )
        if incompatible_request:
            raise PlanValidationError("incompatible_request")
        system = ("你是 Web 应用架构师。输出 JSON：title、pages（name/purpose）、features、data_model、acceptance、tasks、limitations。"
                  "数组成员除 pages 外均为字符串。固定 React+TypeScript+Vite；生成应用业务数据只通过项目存储适配器使用共享 origin 的 localStorage，"
                  "同一项目跨版本复用该 origin。不得设计服务端业务 CRUD、SQL、缓存、外部接口或第三方库。"
                  "若需求要刷新后保留业务数据，data_model 必须逐项写明由 localStorage 保存的字段，acceptance 必须包含刷新读回；不能把数据模型留空或只写页面状态。"
                  "limitations 不得与前述存储方案冲突；浏览器清除存储或更换浏览器后数据无法恢复，业务数据不随代码版本回滚。"
                  "源码采用 src/App.tsx 入口、src/app.css 样式入口；简单状态和业务逻辑可直接放在 App.tsx，复杂逻辑可拆到 src/hooks/，多组件可拆到 src/components/；根目录 readme.md 描述项目。计划须具体可测试。")
        if base_spec:
            system += ("这是对已保存版本的迭代。features 只列本轮新增功能；不要复写原功能。"
                       "如用户明确要求删除或替换旧功能，使用 removed_features 字符串数组、modified_features 对象（旧功能原文到新功能）；"
                       "旧功能原文须逐字匹配。返回 changed_files（需重写的已有生成文件）和 new_files（新增生成文件），路径限固定模板。"
                       "没有明确删除或替换请求时，这两项为空；原数据模型和验收点会自动保留。")
        prompt = (f"本轮需求：{state['request_text']}\n已确认问答：{dumps(state.get('clarification_history', []))}"
                  + (f"\n上一可用版本的完整已确认规格：{dumps(base_spec)}" if base_spec else ""))
        prompt += (f"\n计划修改意见：{state.get('plan_feedback', '')}"
                  "\n请输出完整 Build Plan JSON。")
        last_error: ValueError | None = None
        for correction in range(2):
            raw = self.model.generate(run_id, "plan", f"v{revision}-s{state['spec_version']}-c{correction}", system,
                                      prompt + (f"\n前版计划校验失败：{last_error}" if last_error else ""), max_tokens=4000)
            self._check_cancel(run_id)
            try:
                plan = merge_iteration_plan(raw, base_spec) if base_spec else normalize_plan(raw)
                answered_text = "；".join(str(item.get("answer", "")) for item in state.get("clarification_history", []) if isinstance(item, dict))
                persistence_pattern = re.compile(r"localStorage|持久|保存到|刷新.{0,12}(?:保留|读回|恢复|仍|存在)", re.IGNORECASE)
                persistence_requested = any(
                    not negation.search(clause[:match.start()].rstrip())
                    for clause in re.split(r"[，,。；;\n]", state["request_text"] + "；" + answered_text)
                    for match in persistence_pattern.finditer(clause)
                )
                if persistence_requested:
                    if not any(re.search(r"\blocalStorage\b", item, re.IGNORECASE) for item in plan["data_model"]):
                        raise ValueError("需要持久化的计划必须在数据模型中明确使用项目存储适配器与 localStorage")
                    if not any(re.search(r"刷新|重开|重新进入", item) for item in plan["acceptance"]):
                        raise ValueError("需要持久化的计划必须验收刷新或重进后的数据读回")
                    if any(re.search(r"(?:不使用|不用|禁止|不得|避免|不采用).{0,8}(?:浏览器存储|本地存储|localStorage)", item, re.IGNORECASE)
                           for item in plan["limitations"]):
                        raise ValueError("计划限制与 localStorage 持久化边界冲突")
                break
            except ValueError as exc:
                last_error = exc
                detail_code = plan_validation_error_code(exc)
                self.store.update_run(run_id, event_type="plan_validation_failed", event_payload={
                    "reason_code": detail_code, "reason": PLAN_VALIDATION_REASONS[detail_code]})
        else:
            raise PlanValidationError(plan_validation_error_code(last_error) if last_error else "invalid_plan")
        version = state["spec_version"] + 1
        card_id = str(uuid.uuid4())
        card = {"type": "build_plan", "schema_version": 1, "card_id": card_id, "run_id": run_id, "status": "pending", "payload": plan, "actions": ["approve_plan", "revise_plan"]}
        self.store.update_run(run_id, status="awaiting_plan", phase="WaitPlan", card_json=dumps(card), card_id=card_id,
                              spec_version=version, plan_json=dumps(plan), event_type="card", event_payload={"card": card})
        return {"plan": plan, "card_id": card_id, "spec_version": version, "plan_feedback": "", "plan_action": ""}

    def wait_plan(self, state: RunState) -> dict[str, Any]:
        decision = interrupt({"type": "build_plan", "card_id": state["card_id"], "spec_version": state["spec_version"]})
        if decision.get("action") == "revise_plan":
            return {"plan_action": "revise_plan", "plan_feedback": str(decision.get("feedback", "")).strip()[:2000], "plan_revision": state.get("plan_revision", 0) + 1}
        return {"plan_action": "approve_plan", "plan_feedback": ""}

    def prepare(self, state: RunState) -> dict[str, Any]:
        self._check_execution_time(state["run_id"])
        run = self.store.get_run(state["run_id"])
        if run["approved_spec_version"] != state["spec_version"]:
            raise RuntimeError("计划尚未确认，禁止写入生成文件")
        self.store.update_run(state["run_id"], status="building", phase="Prepare", event_type="phase", event_payload={"phase": "Prepare"})
        self.runner.prepare(state["project_id"], state["run_id"])
        if run.get("base_version_id"):
            base = self.store.get_version(run["base_version_id"])
            if base.get("manifest", {}).get("template") != "react-vite-v4":
                self.store.update_run(state["run_id"], event_type="legacy_base_regeneration", event_payload={
                    "base_version_id": run["base_version_id"],
                    "reason": "旧版未使用项目存储前缀，本轮按合并后的完整计划重新生成"})
                return {}
            files: dict[str, str] = {}
            for entry in base["manifest"].get("files", []):
                if not isinstance(entry, dict):
                    continue
                path = entry.get("path", "")
                if not GENERATED_FILE.fullmatch(path):
                    continue
                content, _ = self.store.get_version_file(base["id"], path)
                if hashlib.sha256(content.encode("utf-8")).hexdigest() != entry.get("sha256"):
                    raise RuntimeError("上一版本源码校验失败，已停止迭代")
                if path == TEMPLATE_STORAGE_FILE:
                    # The runner injects this trusted template file into the new workspace.
                    # It is part of the saved snapshot, but never an Agent-generated file.
                    continue
                files[path] = content
            if self.runner.inspect_generated(files):
                raise RuntimeError("上一版本源码不符合当前生成边界，已停止迭代")
            changed = state["plan"].get("changed_files") or []
            new = state["plan"].get("new_files") or []
            if any(path not in files for path in changed) or any(path in files for path in new):
                raise RuntimeError("计划中的修改文件与上一版本源码不匹配")
            targets = sorted(set(changed + new)) if changed or new else sorted(files)
            ref = f"base-{run['base_version_id']}"
            self.store.cache_set(state["run_id"], "source_candidate", ref, {"files": files})
            self.store.update_run(state["run_id"], event_type="base_version_loaded", event_payload={
                "base_version_id": run["base_version_id"], "target_files": targets})
            return {"source_candidate_ref": ref, "code_feedback": {"target_files": targets}}
        return {}

    def code_loop(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        candidate_number = state.get("candidate_number", 0) + 1
        self.model.check_limits(run_id)
        self.store.update_run(run_id, status="building", phase="CodeLoop", fix_rounds=state.get("fix_rounds", 0),
                              event_type="phase", event_payload={"phase": "CodeLoop", "fix_round": state.get("fix_rounds", 0)})
        feedback = state.get("code_feedback") or {}
        base_ref = state.get("source_candidate_ref")
        base = self.store.cache_get(run_id, "source_candidate", base_ref) if base_ref else None
        targets = feedback.get("target_files") or []
        if not (base and isinstance(base.get("files"), dict) and targets and
                all(isinstance(path, str) and GENERATED_FILE.fullmatch(path) for path in targets)):
            targets = []
        targets = sorted(set(targets))
        base_system = source_contract_prompt(targets)
        prompt = f"批准计划：{dumps(state['plan'])}\n原始需求：{state['request_text']}\n已确认问答：{dumps(state.get('clarification_history', []))}"
        if self.store.get_run(run_id).get("base_version_id"):
            prompt += "\n这是已保存版本的迭代，必须保留批准计划中的沿用功能、数据格式与旧验收点；只按本轮变化调整目标文件。"
        if feedback:
            prompt += f"\n上次检查的问题与修复反馈：{dumps(feedback.get('issues', []))}"
        if targets:
            prompt += f"\n仅重新生成这些文件的完整内容：{dumps(targets)}。其余候选文件保持原样；请遵守现有文件的导入路径。"
            prompt += f"\n待修改文件的上一版完整内容（新文件为空）：{dumps({path: base['files'].get(path, '') for path in targets})}"
            references = repair_interface_context(base["files"], targets)
            if references:
                prompt += ("\n以下是当前候选中保持不变的导入依赖，只供核对导出、props 和 hook 返回值；"
                           f"不得输出或修改这些文件：{dumps(references)}")
        elif feedback:
            prompt += "\n无法可靠定位修改文件，请重新生成完整 files 映射。"
        if state.get("repair_instruction"):
            prompt += f"\n用户指定的修复方向：{state['repair_instruction']}\n不得改变已批准的需求、技术模板或数据持久化边界。"
        cache_key = f"candidate-{candidate_number}"
        raw = self.model.generate(run_id, "code_loop", cache_key, base_system, prompt,
                                  max_tokens=8000 if targets else 16000)
        self._check_cancel(run_id)
        # Fake model adapters do not persist outputs themselves. The immutable
        # cache reference lets ValidateSource resume without storing code in state.
        self.store.cache_set(run_id, "code_loop", cache_key, raw)
        return {"model_output_key": cache_key, "model_output_mode": "partial" if targets else "full",
                "model_output_targets": targets, "candidate_number": candidate_number}

    @staticmethod
    def _repair_history(state: RunState) -> list[list[str]]:
        saved = state.get("repair_failure_history")
        if saved is not None:
            return list(saved)
        return [[f"build:{signature}" for signature in attempt] for attempt in state.get("build_failure_history", [])]

    def validate_source(self, state: RunState) -> dict[str, Any]:
        run_id = state["run_id"]
        self._check_cancel(run_id)
        self.store.update_run(run_id, phase="ValidateSource", event_type="phase", event_payload={"phase": "ValidateSource"})
        raw = self.store.cache_get(run_id, "code_loop", state["model_output_key"])
        submitted = raw.get("files") if isinstance(raw, dict) else None
        targets = state.get("model_output_targets") or []
        mode = state.get("model_output_mode")
        files: dict[str, str] | None = None
        issues: list[dict[str, Any]] = []
        if not isinstance(submitted, dict):
            issues = [{"code": "missing_files_mapping", "file": None}]
        elif mode == "partial" and set(submitted) != set(targets):
            issues = [{"code": "invalid_partial_files", "file": None}]
        elif mode == "partial":
            base = self.store.cache_get(run_id, "source_candidate", state.get("source_candidate_ref", ""))
            if not base or not isinstance(base.get("files"), dict):
                issues = [{"code": "missing_files_mapping", "file": None}]
            else:
                files = {**base["files"], **submitted}
        else:
            files = submitted
        candidate_ref = state.get("source_candidate_ref", "")
        if files is not None:
            candidate_ref = state["model_output_key"]
            self.store.cache_set(run_id, "source_candidate", candidate_ref, {"files": files})
            issues = self.runner.inspect_generated(files)
        if not issues and files is not None:
            written = self.runner.write_generated(state["project_id"], run_id, files, state["candidate_number"])
            self.store.update_run(run_id, event_type="source_validation_passed", event_payload={
                "candidate": state["candidate_number"], "mode": mode, "modified_files": targets if targets else sorted(files),
            })
            return {"source_ok": True, "source_candidate_ref": candidate_ref, "source_feedback": {},
                    "code_feedback": {}, "source_stop_code": "", "stop_reason": "", "written_files": written}
        feedback = repair_feedback(issues, origin="source")
        history = self._repair_history(state)
        history.append(source_signatures(issues))
        hard_stop = any(issue["code"] == "unsafe_capability" for issue in issues)
        stop_reason, stop_code = repair_stop_reason(history, state.get("fix_rounds", 0),
                                                     effective_limits(self.store.get_run(run_id))["fix_rounds"], stage="源码校验")
        if hard_stop:
            stop_reason, stop_code = "候选源码使用了不允许的能力，已停止自动生成。", "unsafe_capability"
        elif state.get("repair_action"):
            stop_reason, stop_code = "本次人工指定的源码修复仍未通过校验，请检查反馈后再决定。", "manual_attempt_failed"
        next_round = state.get("fix_rounds", 0) if stop_code else state.get("fix_rounds", 0) + 1
        self.store.update_run(run_id, fix_rounds=next_round, event_type="source_validation_failed", event_payload={
            "attempt": state["candidate_number"], "reason_code": issues[0]["code"],
            "reason_codes": [issue["code"] for issue in issues], "target_files": feedback["target_files"],
            "issues": feedback["issues"], "mode": feedback["mode"], "stop_code": stop_code,
        })
        return {"source_ok": False, "source_candidate_ref": candidate_ref,
                "source_feedback": feedback, "code_feedback": feedback,
                "repair_failure_history": history, "fix_rounds": next_round,
                "source_stop_code": stop_code, "stop_reason": stop_reason}

    @staticmethod
    def route_source(state: RunState) -> str:
        if state.get("source_ok"):
            return "build_test"
        return "needs_user" if state.get("source_stop_code") else "code_loop"

    def build_test(self, state: RunState) -> dict[str, Any]:
        self._check_execution_time(state["run_id"])
        if self.store.get_run(state["run_id"])["cancel_requested"]:
            raise RunCancelled("任务已取消")
        self.store.update_run(state["run_id"], phase="BuildTest", event_type="phase", event_payload={"phase": "BuildTest"})
        result = self.runner.build(state["project_id"], state["run_id"])
        self._check_cancel(state["run_id"])
        diagnosis = classify_build_failure(result, state["run_id"])
        history = list(state.get("build_failure_history") or [])
        repair_history = self._repair_history(state)
        signatures: list[str] = []
        stop_reason, stop_code = "", ""
        feedback: dict[str, Any] = {}
        if not result["ok"]:
            signatures = error_fingerprints(result, diagnosis["category"])
            history.append(signatures)
            repair_history.append([f"build:{signature}" for signature in signatures])
            candidate = self.store.cache_get(state["run_id"], "source_candidate", state.get("source_candidate_ref", ""))
            candidate_files = set((candidate or {}).get("files") or {})
            feedback = build_repair_feedback(result, candidate_files)
            if diagnosis.get("repairable") and not state.get("repair_action"):
                stop_reason, stop_code = repair_stop_reason(repair_history, state.get("fix_rounds", 0),
                                                             effective_limits(self.store.get_run(state["run_id"]))["fix_rounds"])
            self.store.update_run(state["run_id"], event_type="build_harness", event_payload={
                "attempt": len(history), "fingerprints": signatures, "stop_code": stop_code,
                "automatic_repairs": state.get("fix_rounds", 0), "repairable": diagnosis.get("repairable", False),
            })
        self.store.update_run(state["run_id"], event_type="build_result", event_payload={"ok": result["ok"], "steps": result["steps"], "diagnostics": result["diagnostics"][-1000:]})
        if not result["ok"]:
            self.store.update_run(state["run_id"], event_type="build_diagnosis", event_payload=diagnosis)
        try:
            self.store.record_build_check(
                state["run_id"], attempt=len(history) + (1 if result["ok"] else 0),
                outcome="passed" if result["ok"] else "failed", category=diagnosis["category"],
                command=diagnosis.get("command") or ((result.get("steps") or [{}])[-1]).get("command", ""),
                exit_code=((result.get("steps") or [{}])[-1]).get("exit_code"),
                duration_seconds=sum(float(step.get("seconds") or 0) for step in result.get("steps") or []),
                fix_round=state.get("fix_rounds", 0), fingerprints=signatures,
                target_files=feedback.get("target_files") or [],
                error_codes=sorted(set(re.findall(r"\berror (TS\d{4})\b", str(result.get("diagnostics", ""))))),
                stop_code=stop_code,
            )
        except Exception:
            logger.warning("Build telemetry could not be recorded", exc_info=True)
        return {"build_result": result, "build_ok": result["ok"], "diagnosis": diagnosis,
                "build_failure_history": history, "repair_failure_history": repair_history,
                "code_feedback": feedback, "stop_reason": stop_reason, "build_stop_code": stop_code}

    def route_build(self, state: RunState) -> str:
        if state["build_ok"]:
            return "package_candidate"
        return "diagnose" if (state.get("diagnosis", {}).get("repairable") and not state.get("repair_action")
                              and not state.get("build_stop_code") and state.get("fix_rounds", 0) < effective_limits(self.store.get_run(state["run_id"]))["fix_rounds"]) else "needs_user"

    def diagnose(self, state: RunState) -> dict[str, Any]:
        next_round = state.get("fix_rounds", 0) + 1
        self.store.update_run(state["run_id"], phase="Diagnose", fix_rounds=next_round,
                              event_type="phase", event_payload={"phase": "Diagnose", "fix_round": next_round, "diagnosis": state.get("diagnosis")})
        return {"fix_rounds": next_round}

    def package_candidate(self, state: RunState) -> dict[str, Any]:
        self._check_execution_time(state["run_id"])
        run_id = state["run_id"]
        self._check_cancel(run_id)
        self.store.update_run(run_id, phase="PackageCandidate", event_type="phase", event_payload={"phase": "PackageCandidate"})
        candidate = self.runner.package_candidate(state["project_id"], run_id, state["build_result"])
        return {"candidate": candidate}

    def preview_check(self, state: RunState) -> dict[str, Any]:
        self._check_execution_time(state["run_id"])
        run_id = state["run_id"]
        self._check_cancel(run_id)
        self.store.update_run(run_id, phase="PreviewCheck", event_type="phase", event_payload={"phase": "PreviewCheck"})
        result = self.runner.probe_candidate(state["project_id"], run_id, state["candidate"]["digest"])
        self.store.update_run(run_id, event_type="preview_check", event_payload=result)
        return {"preview_ok": result["ok"], "preview_result": result,
                "stop_reason": "预览检查未通过：" + result["reason"] if not result["ok"] else ""}

    def commit_version(self, state: RunState) -> dict[str, Any]:
        self._check_execution_time(state["run_id"])
        run_id = state["run_id"]
        self._check_cancel(run_id)
        self.store.update_run(run_id, phase="CommitVersion", event_type="phase", event_payload={"phase": "CommitVersion"})
        candidate = state["candidate"]
        manifest = {**candidate["manifest"], "preview": {"status": "checked", **state["preview_result"]}}
        run = self.store.get_run(run_id)
        inherited = (run.get("base_spec") or {}).get("requests") or ([run["base_spec"]["request_text"]] if run.get("base_spec") else [])
        manifest["effective_spec"] = {"request_text": run["request_text"], "requests": (inherited + [run["request_text"]])[-5:],
                                      "plan": state["plan"]}
        manifest["base_version_id"] = run.get("base_version_id")
        self._check_cancel(run_id)
        from .azure_artifacts import collect_candidate_files
        files = collect_candidate_files(self.runner.candidate(state["project_id"], run_id, candidate["digest"]), manifest)
        version, _ = self.store.commit_version_with_files(state["project_id"], run_id, manifest, files)
        self.store.update_run(run_id, status="completed", phase="Done", version_id=version["id"], card_json=dumps({
            "type": "test_result", "schema_version": 1, "card_id": str(uuid.uuid4()), "run_id": run_id,
            "status": "passed", "payload": {"version_id": version["id"], "build": manifest["build"], "files": manifest["files"],
            "diagnostics_ref": f"/api/runs/{run_id}/build-log", "browser_check": "not_run", "preview_check": state["preview_result"]}, "actions": []
        }), event_type="completed", event_payload={"version_id": version["id"]})
        self._cleanup_artifacts()
        return {"version_id": version["id"]}

    def needs_user(self, state: RunState) -> dict[str, Any]:
        build = state.get("build_result") or {}
        diagnosis = state.get("diagnosis") or {}
        source_failure = bool(state.get("source_stop_code") and state.get("source_ok") is False)
        error = state.get("stop_reason") or diagnosis.get("reason") or build.get("diagnostics", "")[-2000:] or "本轮未能完成检查"
        build_failure = bool(build and not build.get("ok")) and not source_failure
        summary = (source_failure_summary(self.store.events(state["run_id"]), error, state.get("fix_rounds", 0))
                   if source_failure else build_failure_summary(self.store.events(state["run_id"]), diagnosis,
                       state.get("fix_rounds", 0)) if build_failure else None)
        if summary and state.get("build_stop_code"):
            if build_failure:
                summary["cause"] = str(error)
        card = self._failure_card(state["run_id"], error, build.get("steps", []), diagnosis)
        waitable_source = source_failure and state.get("source_stop_code") != "unsafe_capability"
        if build_failure or waitable_source:
            card["status"] = "pending"
            card["payload"]["failure_summary"] = summary
            card["payload"]["failure_stage"] = "source_validation" if source_failure else "build"
            card["payload"]["stop_code"] = state.get("source_stop_code") if source_failure else state.get("build_stop_code") or None
            card["payload"]["manual_rounds"] = state.get("manual_rounds", 0)
            card["actions"] = (["continue_repair", "guided_repair"] if source_failure or diagnosis.get("repairable") else []) + ([] if source_failure else ["rebuild"])
            if card["payload"]["stop_code"] == "repair_limit":
                card["actions"].append("extend_auto_repair")
        elif source_failure:
            card["payload"]["failure_summary"] = summary
            card["payload"]["failure_stage"] = "source_validation"
        card_id = card["card_id"]
        repair_waiting = build_failure or waitable_source
        version = state.get("spec_version", 0) + 1 if repair_waiting else state.get("spec_version", 0)
        self.store.update_run(state["run_id"], status="awaiting_repair" if repair_waiting else "failed", phase="WaitRepair" if repair_waiting else "NeedsUser",
                              error=error, card_json=dumps(card), card_id=card_id, spec_version=version,
                              event_type="card" if repair_waiting else "failed",
                              event_payload={"card": card} if repair_waiting else {"reason": state.get("source_stop_code") if source_failure else diagnosis.get("category", "requirements_incomplete")})
        if source_failure:
            issue_codes = tuple(issue["code"] for issue in (state.get("source_feedback") or {}).get("issues", []))
            self._capture_failure(state["run_id"], source="agent", phase="ValidateSource", code="unsafe_source",
                                  exception_type="UnsafeSource", source_validation_codes=issue_codes)
        elif build_failure:
            stop_codes = {"no_progress": "build_no_progress", "recurring_error": "build_recurring_error",
                          "repair_limit": "build_repair_limit"}
            self._capture_failure(state["run_id"], source="build", phase="BuildTest",
                                  code=stop_codes.get(state.get("build_stop_code", ""), "build_failed"),
                                  exception_type="BuildFailure")
        elif state.get("preview_ok") is False:
            self._capture_failure(state["run_id"], source="agent", phase="PreviewCheck",
                                  code="preview_failed", exception_type="PreviewFailure")
        return {"card_id": card_id, "spec_version": version, "repair_waiting": repair_waiting} if repair_waiting else {"repair_waiting": False}

    def wait_repair(self, state: RunState) -> dict[str, Any]:
        decision = interrupt({"type": "test_result", "card_id": state["card_id"], "spec_version": state["spec_version"]})
        action = decision["action"]
        if action == "extend_auto_repair":
            return {"repair_action": "", "repair_instruction": "", "manual_rounds": state.get("manual_rounds", 0)}
        return {"repair_action": action,
                "repair_instruction": str(decision.get("feedback", "")).strip()[:2000] if action == "guided_repair" else "",
                "manual_rounds": state.get("manual_rounds", 0) + 1}

    def present_run(self, run: dict[str, Any]) -> dict[str, Any]:
        """Give older terminal build failures the same evidence summary before opting in."""
        run = {**run, "active_elapsed_seconds": self.store.active_elapsed_seconds(run["id"]),
               "execution_running": bool(run.get("execution_started_at") and run["status"] in {"clarifying", "planning", "building"})}
        run["needs_model_key"] = bool(isinstance(self.model, ModelGateway)
            and self.store.operation_get(run["id"], "user_model_config")
            and not self.model.has_run_credentials(run["id"])
            and run["status"] in {"clarifying", "planning", "building"})
        card = run.get("card") or {}
        if (run["status"] == "failed" and self.store.latest_exception_code(run["id"]) == "model_output_invalid"):
            config = {"configurable": {"thread_id": run["id"]}}
            snapshot = self.graph.get_state(config)
            state = snapshot.values or {}
            build = state.get("build_result") or {}
            diagnosis = state.get("diagnosis") or {}
            if (snapshot.next == ("code_loop",) and build.get("ok") is False and diagnosis.get("repairable")
                    and self.store.can_reopen_failed_run(run["id"])):
                result = {**run, "card": {**card, "payload": {**(card.get("payload") or {})}}}
                result["card"]["payload"].update({
                    "build": {"ok": False, "steps": build.get("steps") or []},
                    "failure_stage": "build",
                    "failure_summary": build_failure_summary(self.store.events(run["id"]), diagnosis, run["fix_rounds"]),
                })
                result["card"]["payload"]["failure_summary"]["cause"] = (
                    "模型在修复构建错误时返回了无法解析的输出；保留了上次候选和构建记录。")
                blocker = self._recovery_blocker(state)
                if blocker:
                    result["card"]["payload"]["recovery_blocker"] = blocker
                elif self.store.active_elapsed_seconds(run["id"]) < effective_limits(run)["run_seconds"]:
                    result["card"]["actions"] = ["open_repair"]
                return result
        if run["status"] != "failed" or card.get("type") != "test_result" or (card.get("payload") or {}).get("build", {}).get("ok") is not False or not card["payload"]["build"].get("steps"):
            return run
        result = {**run, "card": {**card, "payload": {**card["payload"]}}}
        result["card"]["payload"]["failure_summary"] = build_failure_summary(self.store.events(run["id"]),
            card["payload"].get("diagnosis") or {}, run["fix_rounds"])
        state = self.graph.get_state({"configurable": {"thread_id": run["id"]}}).values or {}
        blocker = self._recovery_blocker(state)
        if blocker:
            result["card"]["payload"]["recovery_blocker"] = blocker
        elif self.store.can_reopen_failed_run(run["id"]) and self.store.active_elapsed_seconds(run["id"]) < effective_limits(run)["run_seconds"] and state.get("build_result"):
            result["card"]["actions"] = ["open_repair"]
        return result

    @staticmethod
    def _recovery_blocker(state: dict[str, Any]) -> str:
        plan = state.get("plan")
        if not plan:
            return "历史运行没有可核对的已批准计划，请修改需求后开始新一轮。"
        try:
            normalize_plan(plan)
        except ValueError as exc:
            if "localStorage" in str(exc):
                return "这条历史运行的已批准计划与当前交付物边界冲突；原计划依赖已移除的服务端业务存储。请修改需求，改用 localStorage 后开始新一轮。"
            return "这条历史运行的计划不符合当前模板要求。请核对需求后开始新一轮。"
        return ""

    def offer_repair(self, run_id: str) -> dict[str, Any]:
        """Reopen a legacy terminal build checkpoint by explicit owner action."""
        with self.store.lock:
            run = self.store.get_run(run_id)
            if run["status"] == "awaiting_repair":
                return run
            if not self.store.can_reopen_failed_run(run_id):
                raise ValueError("只有当前项目最近一次已结束的构建失败可继续修复")
            config = {"configurable": {"thread_id": run_id},
                      "recursion_limit": max(100, effective_limits(run)["fix_rounds"] * 4 + 30)}
            snapshot = self.graph.get_state(config)
            state = snapshot.values
            build = state.get("build_result") or {}
            card_payload = (run.get("card") or {}).get("payload") or {}
            model_output_recovery = (self.store.latest_exception_code(run_id) == "model_output_invalid"
                                     and snapshot.next == ("code_loop",) and (state.get("diagnosis") or {}).get("repairable"))
            if not card_payload.get("build", {}).get("steps") and not model_output_recovery:
                raise ValueError("这条运行没有可恢复的构建记录")
            if not build or build.get("ok") or self.store.active_elapsed_seconds(run_id) >= effective_limits(run)["run_seconds"]:
                raise ValueError("当前失败没有可恢复的构建候选或执行预算已用尽")
            blocker = self._recovery_blocker(state)
            if blocker:
                raise ValueError(blocker)
            diagnosis = state.get("diagnosis") or classify_build_failure(build, run_id)
            summary = build_failure_summary(self.store.events(run_id), diagnosis, state.get("fix_rounds", 0))
            if model_output_recovery:
                summary["cause"] = "模型在修复构建错误时返回了无法解析的输出；可以依据已保留的候选继续修复。"
            card = self._failure_card(run_id, run.get("error") or diagnosis.get("reason", "构建失败"), build.get("steps", []), diagnosis)
            card["status"] = "pending"
            card["payload"]["failure_summary"] = summary
            card["payload"]["manual_rounds"] = state.get("manual_rounds", 0)
            card["actions"] = (["continue_repair", "guided_repair"] if diagnosis.get("repairable") else []) + ["rebuild"]
            if state.get("build_stop_code") == "repair_limit":
                card["actions"].append("extend_auto_repair")
            version = run["spec_version"] + 1
            self.graph.update_state(config, {"card_id": card["card_id"], "spec_version": version}, as_node="needs_user")
            if self.graph.get_state(config).next != ("wait_repair",):
                raise RuntimeError("构建检查点无法恢复到人工修复节点")
            return self.store.update_run(run_id, status="awaiting_repair", phase="WaitRepair", card_json=dumps(card),
                card_id=card["card_id"], spec_version=version, event_type="card", event_payload={"card": card})

    @staticmethod
    def _budget_resume_status(phase: str) -> str:
        if phase in {"Clarify", "ClarityGate", "WaitClarify"}:
            return "clarifying"
        if phase in {"Plan", "WaitPlan"}:
            return "planning"
        return "building"

    def _budget_card(self, run: dict[str, Any], *, reason: str, kind: str,
                     resume_phase: str) -> dict[str, Any]:
        return {"type": "budget_extension", "schema_version": 1,
                "card_id": str(uuid.uuid4()), "run_id": run["id"], "status": "pending",
                "payload": {"reason": reason, "budget_kind": kind,
                            "limits": effective_limits(run),
                            "usage": {"model_calls": run["model_calls"], "total_tokens": run["tokens_used"],
                                      "run_seconds": math.ceil(self.store.active_elapsed_seconds(run["id"])) if run.get("active_seconds") is not None else None,
                                      "fix_rounds": run["fix_rounds"]},
                            "increments": EXTENSION_STEPS,
                            "resume_phase": resume_phase,
                            "resume_status": self._budget_resume_status(resume_phase)},
                "actions": ["extend_budget"]}

    def offer_budget(self, run_id: str) -> dict[str, Any]:
        """Expose an older budget stop for owner-confirmed, checkpointed continuation."""
        with self.store.lock:
            run = self.store.get_run(run_id)
            if run["status"] == "awaiting_budget":
                return run
            if not self.store.can_offer_budget(run_id):
                raise ValueError("只能继续当前项目最近一次达到额度上限的任务")
            snapshot = self.graph.get_state({"configurable": {"thread_id": run_id}})
            if not snapshot.next and snapshot.values:
                raise ValueError("原任务没有可继续的执行检查点")
            resume_phase = self.store.budget_pause_phase(run_id)
            if not resume_phase or resume_phase in {"Unknown", "NeedsUser", "WaitBudget"}:
                next_node = snapshot.next[0] if snapshot.next else "clarify"
                resume_phase = {"plan": "Plan", "clarify": "Clarify", "clarity_gate": "ClarityGate",
                                "code_loop": "CodeLoop", "validate_source": "ValidateSource",
                                "build_test": "BuildTest", "diagnose": "Diagnose",
                                "package_candidate": "PackageCandidate", "preview_check": "PreviewCheck",
                                "commit_version": "CommitVersion"}.get(next_node, "Prepare")
            reason = str(run.get("error") or "本次任务达到额度上限。")[:300]
            kind = ("output_reserve" if "Token 余量" in reason else
                    "total_tokens" if "Token" in reason else
                    "model_calls" if "调用次数" in reason else
                    "run_seconds" if "执行" in reason else "unknown")
            card = self._budget_card(run, reason=reason, kind=kind, resume_phase=resume_phase)
            return self.store.update_run(run_id, status="awaiting_budget", phase="WaitBudget",
                card_json=dumps(card), card_id=card["card_id"], spec_version=run["spec_version"] + 1,
                event_type="card", event_payload={"card": card})

    def _capture_failure(self, run_id: str, *, source: str, phase: str,
                         code: str, exception_type: str,
                         budget_detail: tuple[str, int, int] | None = None,
                         source_validation_codes: tuple[str, ...] | None = None,
                         plan_validation_code: str | None = None,
                         model_output_reason_code: str | None = None) -> None:
        try:
            run = self.store.get_run(run_id)
            self.store.record_exception(trace_id=run["trace_id"], project_id=run["project_id"],
                                        run_id=run_id, source=source, phase=safe_phase(phase),
                                        code=code, exception_type=exception_type,
                                        budget_detail=budget_detail,
                                        source_validation_codes=source_validation_codes,
                                        plan_validation_code=plan_validation_code,
                                        model_output_reason_code=model_output_reason_code)
        except Exception:
            # Telemetry must not change the run outcome or expose the failing payload.
            logger.warning("Exception metadata capture failed for terminal run")

    def _check_cancel(self, run_id: str) -> None:
        self._check_execution_time(run_id)
        if self.store.get_run(run_id)["cancel_requested"]:
            raise RunCancelled("任务已取消")

    def _check_execution_time(self, run_id: str) -> None:
        active_seconds = self.store.active_elapsed_seconds(run_id)
        limit = effective_limits(self.store.get_run(run_id))["run_seconds"]
        if active_seconds >= limit:
            raise BudgetExceeded("run_seconds", observed=math.ceil(active_seconds),
                                 limit=limit)

    @staticmethod
    def _failure_card(run_id: str, error: str, steps: list[dict[str, Any]] | None = None,
                      diagnosis: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"type": "test_result", "schema_version": 1, "card_id": str(uuid.uuid4()), "run_id": run_id,
                "status": "failed", "payload": {"build": {"ok": False, "steps": steps or []},
                "diagnostics": error[-2000:], "diagnostics_ref": f"/api/runs/{run_id}/build-log" if steps else None,
                "browser_check": "not_run_mvp1", "diagnosis": diagnosis or None}, "actions": []}

    def enqueue(self, run_id: str) -> None:
        with self.queue_lock:
            if run_id in self.queued:
                return
            self.queued.add(run_id)
        self.executor.submit(self._process, run_id)

    def _process(self, run_id: str) -> None:
        started = False
        budget_paused = False
        heartbeat_stop = threading.Event()
        heartbeat_thread: threading.Thread | None = None
        try:
            run = self.store.get_run(run_id)
            if run["status"] not in {"clarifying", "planning", "building"}:
                return
            started = self.store.begin_execution(run_id)
            if not started:
                return
            heartbeat_thread = threading.Thread(target=self._heartbeat_execution,
                                                args=(run_id, heartbeat_stop), daemon=True)
            heartbeat_thread.start()
            self._check_execution_time(run_id)
            config = {"configurable": {"thread_id": run_id},
                      "recursion_limit": max(100, effective_limits(run)["fix_rounds"] * 4 + 30)}
            pending = self.store.pending_decision(run_id)
            snapshot = self.graph.get_state(config)
            if pending and snapshot.next and snapshot.next[0] in {"wait_clarification", "wait_plan", "wait_repair"}:
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
            budget_paused = True
            current = self.store.get_run(run_id)
            previous_phase = current["phase"]
            reason = str(exc)
            card = self._budget_card(current, reason=reason, kind=exc.kind, resume_phase=previous_phase)
            self.store.update_run(run_id, status="awaiting_budget", phase="WaitBudget", error=reason,
                                  card_json=dumps(card), card_id=card["card_id"],
                                  spec_version=current["spec_version"] + 1,
                                  event_type="budget_exceeded", event_payload={"reason": reason, "kind": exc.kind})
            self.store.update_run(run_id, event_type="card", event_payload={"card": card})
            self._capture_failure(run_id, source="agent", phase=previous_phase,
                                  code="budget_exceeded", exception_type="BudgetExceeded",
                                  budget_detail=(exc.kind, exc.observed, exc.limit))
        except Exception as exc:
            previous_phase = self.store.get_run(run_id)["phase"]
            code, kind = classify(exc)
            validation_codes = exc.codes if isinstance(exc, SourceValidationError) else None
            model_output_reason_code = next((item.reason_code for item in cause_chain(exc)
                                             if isinstance(item, ModelOutputError)), None)
            reason = (source_validation_reason(validation_codes) if validation_codes else
                      str(exc) if isinstance(exc, PlanValidationError) else
                      MODEL_OUTPUT_REASONS.get(model_output_reason_code, REASONS[code]) if code == "model_output_invalid"
                      else REASONS[code])
            card = self._failure_card(run_id, reason)
            if previous_phase == "Plan" or isinstance(exc, PlanValidationError):
                card["payload"]["failure_stage"] = "plan"
                card["payload"]["failure_reason_code"] = exc.reason_code if isinstance(exc, PlanValidationError) else code
            elif code == "version_commit_failed":
                card["payload"]["failure_stage"] = "commit_version"
                card["payload"]["failure_reason_code"] = code
            self.store.update_run(run_id, status="failed", phase="NeedsUser", error=reason,
                                  card_json=dumps(card),
                                  event_type="failed", event_payload={"reason": code})
            self._capture_failure(run_id, source="agent", phase=previous_phase,
                                  code=code, exception_type=kind,
                                  source_validation_codes=validation_codes,
                                  plan_validation_code=exc.reason_code if isinstance(exc, PlanValidationError) else None,
                                  model_output_reason_code=model_output_reason_code)
        finally:
            if started:
                heartbeat_stop.set()
                if heartbeat_thread is not None:
                    heartbeat_thread.join(timeout=1)
                try:
                    self.store.finish_execution(run_id)
                except Exception:
                    logger.warning("Execution time checkpoint failed for terminal run")
            with self.queue_lock:
                self.queued.discard(run_id)
            # A decision may arrive after this worker entered the waiting node but
            # before it left the queue. In that case the API's enqueue was skipped.
            run = self.store.get_run(run_id)
            if run["status"] in {"completed", "failed", "cancelled"} and isinstance(self.model, ModelGateway):
                self.model.release_run_credentials(run_id)
            if run["status"] in {"clarifying", "planning", "building"} and (budget_paused or self.store.pending_decision(run_id)):
                self.enqueue(run_id)

    def _heartbeat_execution(self, run_id: str, stop: threading.Event) -> None:
        while not stop.wait(5):
            try:
                self.store.checkpoint_execution(run_id)
            except Exception:
                logger.warning("Execution time heartbeat failed")
                return

    def recover(self) -> None:
        self.store.recover_execution_timers()
        for run in self.store.get_waiting_repair_runs():
            state = self.graph.get_state({"configurable": {"thread_id": run["id"]}}).values or {}
            blocker = self._recovery_blocker(state)
            if blocker:
                card = {**(run.get("card") or {}), "payload": {**((run.get("card") or {}).get("payload") or {})},
                        "actions": [], "status": "failed"}
                card["payload"]["recovery_blocker"] = blocker
                self.store.update_run(run["id"], status="failed", phase="NeedsUser", error=blocker, card_json=dumps(card),
                    event_type="failed", event_payload={"reason": "plan_incompatible"})
        self._cleanup_artifacts()
        for run in self.store.get_recoverable_runs():
            if (isinstance(self.model, ModelGateway)
                    and self.store.operation_get(run["id"], "user_model_config")
                    and not self.model.has_run_credentials(run["id"])):
                continue
            self.enqueue(run["id"])

    def _cleanup_artifacts(self) -> None:
        for project_id, run_id in self.store.pending_artifact_cleanup():
            try:
                self.runner.remove_artifact(project_id, run_id)
                self.store.mark_artifact_cleaned(project_id, run_id)
            except Exception:
                logger.warning("Deferred artifact cleanup will retry on the next startup")
