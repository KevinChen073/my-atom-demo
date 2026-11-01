"""Stage-scoped interpretation of one user submission into an allowed decision."""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .store import Store
from .workflow import Workflow


logger = logging.getLogger(__name__)
CHANGE = re.compile(r"修改|改成|换成|删掉|删除|去掉|不要|增加|新增|调整|只保留|补充|重写|改为|移除|添加|变成|还需要|再加|把")
QUESTION = re.compile(r"[?？]|能否|是否|为什么|请问|怎么|如何")
CONDITION = re.compile(r"如果|只要|前提|条件是|假如")
APPROVE = re.compile(r"(?:按|照|依据|确认|同意).{0,12}(?:这版|当前|这个|上述)?计划.{0,12}(?:开始|生成|构建|制作)|(?:开始|生成|构建).{0,12}(?:这版|当前|这个)?计划")
REBUILD = re.compile(r"(?:现有|当前|原样|不改|不要改|别改).{0,12}(?:代码|文件).{0,12}(?:重新构建|重建)|(?:现有|当前|原样).{0,12}(?:重新构建|重建)|(?:直接重建|直接重新构建)")
CONTINUE_REPAIR = re.compile(r"再修|继续修复|继续改代码|让.{0,8}修复")
REPLACE_REQUEST = "请将原需求完整替换为："


def interpret_submission(message: dict[str, Any], run: dict[str, Any], model: Any) -> tuple[str | None, dict[str, Any], list[str], str]:
    """Model may suggest an intent; deterministic gates own every side effect."""
    text = str(message["text"]).strip()
    answers = message.get("answers") or {}
    card = run.get("card") or {}
    status = run["status"]
    action: str | None = None
    payload: dict[str, Any] = {}
    intents: list[str] = []
    reply = "请说清楚本次希望我做什么。"
    has_change = bool(CHANGE.search(text))
    has_question = bool(QUESTION.search(text) or CONDITION.search(text))
    question_first = bool(re.match(r"^(?:能否|能不能|可不可以|是否|怎么|如何|请问|可以把)", text))

    if status == "awaiting_clarification":
        questions = (card.get("payload") or {}).get("questions") or []
        required_complete = all(
            not question.get("required") or bool(str(answers.get(question["id"], "")).strip())
            for question in questions
        )
        if text.startswith(REPLACE_REQUEST):
            replacement = text[len(REPLACE_REQUEST):].strip()
            if 10 <= len(replacement) <= 5000:
                return "revise_clarification", {"request_text": replacement}, ["revise_requirement"], "已收到修改后的需求，我会重新梳理关键问题。"
            return None, {}, ["revise_requirement"], "修改后的完整需求需要 10–5000 字。"
        if has_change and not question_first:
            revised = f"{run['request_text']}\n补充要求：{text}"
            if len(revised) <= 5000:
                return "revise_clarification", {"request_text": revised}, ["revise_requirement"], "已记录需求调整；本张澄清卡的答案不会被默认为确认。"
            return None, {}, ["revise_requirement"], "需求已接近字数上限，请精简后发送。"
        if has_question:
            return None, {}, ["question"], answer_question(model, message, run)
        if required_complete:
            return "confirm_clarification", {"answers": answers}, ["answer"], "已记录你的回答，正在核对需求是否完整。"
        return None, {}, ["answer"], "请在澄清卡中逐题填写答案；采用建议也要明确点击选择。"

    if status == "awaiting_plan":
        if has_change and not question_first:
            return "revise_plan", {"feedback": text[:2000]}, ["revise_plan", "approve_candidate"] if APPROVE.search(text) else ["revise_plan"], "我会先更新计划；新版计划仍需你再次明确批准。"
        if has_question:
            return None, {}, ["question", "approve_candidate"] if APPROVE.search(text) else ["question"], answer_question(model, message, run)
        if APPROVE.search(text):
            return "approve_plan", {}, ["approve_plan"], "已按当前计划开始生成。"
        if text in {"", "好", "可以", "确认", "继续", "没问题", "同意"}:
            return None, {}, ["ambiguous"], "请明确写出“按这版计划开始生成”，或说明要修改的地方。"
        intents, _ = model_intents(model, message, run, ["revise_plan", "question"])
        return None, {}, intents or ["ambiguous"], "请明确写出“按这版计划开始生成”，或说明要修改的地方。"

    if status == "awaiting_repair":
        allowed = set(card.get("actions") or [])
        if text == "增加30轮自动修复并继续":
            return ("extend_auto_repair", {}, ["extend_auto_repair"], "已增加 30 轮自动修复额度，正在继续当前候选。") if "extend_auto_repair" in allowed else (None, {}, ["extend_auto_repair"], "当前停机原因不支持继续自动修复。")
        rebuild = bool(REBUILD.search(text))
        repair = bool(CONTINUE_REPAIR.search(text))
        if rebuild and repair:
            return None, {}, ["rebuild", "repair"], "这条消息同时要求改代码和原样构建。请只选择一种处理方式。"
        if rebuild:
            return ("rebuild", {}, ["rebuild"], "会用现有代码重新构建一次，不修改源码。") if "rebuild" in allowed else (None, {}, ["rebuild"], "当前失败不支持原样重新构建。")
        if has_question:
            return None, {}, ["question"], answer_question(model, message, run)
        if repair and not has_change:
            return ("continue_repair", {}, ["continue_repair"], "会针对当前构建错误修复一次。") if "continue_repair" in allowed else (None, {}, ["continue_repair"], "当前错误不适合自动修改源码；可在环境恢复后要求原样重新构建。")
        if has_change and not question_first and len(text) >= 3:
            return ("guided_repair", {"feedback": text[:2000]}, ["guided_repair"], "会按你给出的方向修复源码一次。") if "guided_repair" in allowed else (None, {}, ["guided_repair"], "当前错误不适合自动修改源码；可在环境恢复后要求原样重新构建。")
        if text in {"", "继续", "重试", "再来", "可以"}:
            return None, {}, ["ambiguous"], "请明确写“再修复一次”或“用现有代码重新构建，不改文件”。"
        intents, _ = model_intents(model, message, run, ["guided_repair", "continue_repair", "rebuild", "question"])
        return None, {}, intents or ["ambiguous"], "请明确写“再修复一次”或“用现有代码重新构建，不改文件”。"
    return action, payload, intents, reply


def answer_question(model: Any, message: dict[str, Any], run: dict[str, Any]) -> str:
    text = str(message["text"])
    if re.search(r"跨设备|多设备|云同步", text):
        return "当前交付物只在该预览域使用 localStorage 保存业务数据，不支持跨设备同步。当前卡片未被确认。"
    try:
        card = run.get("card") or {}
        raw = model.generate(run["id"], "interpret_question", message["id"],
            "只根据当前卡片和产品边界回答用户的问题，不执行动作、不批准计划。"
            "不得承诺未验证能力。只输出 JSON 对象，字段 reply 为不超过 180 字的中文答复。",
            f"阶段：{run['status']}。卡片：{str(card.get('payload') or {})[:5000]}。用户问题：{text[:2000]}", max_tokens=320)
        reply = str(raw.get("reply", "")).strip()[:180] if isinstance(raw, dict) else ""
        if reply and not re.search(r"已(?:批准|确认|开始生成|开始构建|修复)|正在(?:生成|构建|修复)|计划已获批准", reply):
            return f"{reply} 当前卡片未被确认。"
    except Exception:
        logger.warning("Question interpretation unavailable; leaving decision pending")
    return "暂时无法可靠回答这个问题。请查看当前卡片，或换一种说法；当前卡片未被确认。"


def model_intents(model: Any, message: dict[str, Any], run: dict[str, Any], allowed: list[str]) -> tuple[list[str], str]:
    try:
        raw = model.generate(run["id"], "interpret", message["id"],
            "你只判断当前阶段用户消息的意图，不批准计划、不执行工具。只输出 JSON：intents 字符串数组、reply 简短中文。"
            "若含具体修改与批准，必须同时列出修改与批准候选；问题或条件优先。",
            f"阶段：{run['status']}。允许分类：{allowed}。当前卡标题：{(run.get('card') or {}).get('type', '')}。"
            f"用户原文：{message['text']}", max_tokens=600)
        intents = raw.get("intents") if isinstance(raw, dict) else []
        return [str(item) for item in intents if item in allowed][:4] if isinstance(intents, list) else [], str(raw.get("reply", ""))[:240] if isinstance(raw, dict) else ""
    except Exception:
        logger.warning("Message intent interpretation unavailable; leaving decision pending")
        return [], "暂时没能可靠理解这条消息。请更明确地说明，当前卡片未被确认。"


class MessageService:
    def __init__(self, store: Store, workflow: Workflow):
        self.store, self.workflow = store, workflow
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="myatom-message")
        self.lock = threading.Lock()
        self.queued: set[str] = set()

    def enqueue(self, submission_id: str) -> None:
        with self.lock:
            if submission_id in self.queued:
                return
            self.queued.add(submission_id)
        self.executor.submit(self.process, submission_id)

    def recover(self) -> None:
        for submission_id in self.store.pending_submissions():
            self.enqueue(submission_id)

    def process(self, submission_id: str) -> None:
        started = False
        result: dict[str, Any] | None = None
        run_id = ""
        try:
            message = self.store.get_submission(submission_id)
            if message["status"] != "interpreting":
                return
            run_id = message["run_id"]
            run = self.store.get_run(run_id)
            started = self.store.begin_execution(run_id, allow_waiting=True)
            action, payload, intents, reply = interpret_submission(message, run, self.workflow.model)
            result = self.store.resolve_submission(submission_id, action=action, payload=payload, intents=intents, reply=reply)
        except Exception:
            logger.exception("Message processing failed")
            if run_id:
                result = self.store.resolve_submission(submission_id, action=None, payload={}, intents=[],
                    reply="消息解释暂时失败；当前卡片未被确认，请重新明确发送。")
        finally:
            if started:
                self.store.finish_execution(run_id)
            with self.lock:
                self.queued.discard(submission_id)
        if result and result["status"] == "committed":
            self.workflow.enqueue(run_id)
