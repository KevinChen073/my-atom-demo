from __future__ import annotations

import hashlib
import asyncio
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .messages import MessageService
from .preview_access import PreviewAccess
from .settings import Settings
from .store import Conflict, NotFound, Store
from .workflow import Workflow
from .model import ModelGateway
from .model_credentials import validate_model_credentials
from .invite_auth import InviteAuth


COOKIE = "myatom_guest"
INVITE_COOKIE = "myatom_test"
logger = logging.getLogger(__name__)


class ProjectInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class InviteInput(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class RunInput(BaseModel):
    request_text: str = Field(min_length=10, max_length=5000)
    mode: Literal["auto", "create", "iterate"] = "auto"


class DecisionInput(BaseModel):
    card_id: str
    spec_version: int
    action: str
    answers: dict[str, str] | None = None
    feedback: str | None = None
    request_text: str | None = None


class BudgetExtensionInput(BaseModel):
    card_id: str
    spec_version: int
    model_calls: bool = False
    total_tokens: bool = False
    run_seconds: bool = False
    fix_rounds: bool = False


class CardRef(BaseModel):
    card_id: str
    spec_version: int


class MessageInput(BaseModel):
    submission_id: str
    card_ref: CardRef
    text: str = Field(max_length=5200)
    answers: dict[str, str] = Field(default_factory=dict)
    reply_to_interpretation_id: str | None = None


def owner_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_app(settings: Settings | None = None, model: Any = None) -> FastAPI:
    settings = settings or Settings()
    if settings.app_env not in {"local", "container_smoke", "azure_demo"}:
        raise RuntimeError("不支持的运行环境")
    if settings.app_env == "container_smoke":
        # Health-only mode must boot even when the container already has its
        # future Azure SQL configuration. It never opens that database.
        settings = replace(settings, azure_sql_connection_string="", database_url="")
    settings.validate_azure_demo()
    if settings.azure_sql_connection_string:
        if settings.app_env not in {"local", "azure_demo"}:
            raise RuntimeError("当前运行环境不允许连接 Azure SQL")
        from .azure_sql import AzureSqlStore
        from .preview_access import AzureSqlPreviewAccess
        store = AzureSqlStore(settings.azure_sql_connection_string)
        preview_access = AzureSqlPreviewAccess(settings.azure_sql_connection_string)
    elif settings.database_url:
        if settings.app_env not in {"local", "azure_demo"}:
            raise RuntimeError("当前运行环境不允许连接 PostgreSQL")
        from .postgres_store import PostgresStore
        from .preview_access import PostgresPreviewAccess
        store = PostgresStore(settings.database_url)
        preview_access = PostgresPreviewAccess(settings.database_url)
    else:
        store = Store(settings.app_db)
        preview_access = PreviewAccess(settings.data_dir / "preview_access.sqlite3")
    workflow = Workflow(settings, store, model=model)
    messages = MessageService(store, workflow)
    invite_auth = InviteAuth(settings.invite_code)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        workflow.recover()
        messages.recover()
        yield
        # The checkpointer owns one SQLite connection shared with graph worker
        # threads. Drain active work before closing it, including on TestClient
        # shutdown, or a concurrent put_writes can crash the Python process.
        messages.executor.shutdown(wait=True, cancel_futures=True)
        workflow.executor.shutdown(wait=True, cancel_futures=True)
        workflow.checkpoint_connection.close()

    app = FastAPI(title="MYATOM MVP2", lifespan=lifespan)
    app.state.store = store
    app.state.workflow = workflow
    app.state.messages = messages

    @app.middleware("http")
    async def azure_invite_boundary(request: Request, call_next):
        if settings.app_env == "azure_demo":
            path = request.url.path
            protected = (path == "/api/model/test"
                         or path == "/api/projects" and request.method != "GET"
                         or path.startswith("/api/projects/")
                         or path.startswith("/api/runs/")
                         or path.startswith("/api/versions/")
                         or path == "/preview" or path.startswith("/preview/"))
            if protected and not invite_auth.verify(request.cookies.get(INVITE_COOKIE)):
                return JSONResponse({"detail": "请先输入邀请码进入测试空间"}, status_code=401,
                                    headers={"Cache-Control": "no-store"})
        return await call_next(request)

    if settings.app_env == "container_smoke":
        @app.middleware("http")
        async def smoke_only(request: Request, call_next):
            if request.url.path != "/api/health":
                return JSONResponse({"detail": "容器启动检查模式，应用功能尚未开放"}, status_code=503)
            return await call_next(request)

    @app.exception_handler(NotFound)
    async def not_found(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(_: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        trace_id = str(uuid.uuid4())
        try:
            store.record_exception(trace_id=trace_id, source="api", phase="UnhandledRequest",
                                   code="api_unhandled", exception_type="UnhandledException")
        except Exception:
            logger.warning("Exception metadata capture failed for API request")
        return JSONResponse({"detail": "服务暂时无法完成请求，请稍后重试。", "trace_id": trace_id},
                            status_code=500, headers={"X-Trace-ID": trace_id})

    def active_invite(request: Request) -> str | None:
        return invite_auth.verify(request.cookies.get(INVITE_COOKIE))

    def current_owner(request: Request) -> str | None:
        invited = active_invite(request)
        if invited:
            return invite_auth.owner(invited)
        token = request.cookies.get(COOKIE)
        return owner_hash(token) if token else None

    def require_owner(request: Request) -> str:
        if settings.app_env == "azure_demo" and not active_invite(request):
            raise HTTPException(status_code=401, detail="请先输入邀请码进入测试空间")
        owner = current_owner(request)
        if not owner:
            raise HTTPException(status_code=401, detail="请先创建项目以建立访客身份")
        return owner

    def project_access(request: Request, project_id: str) -> dict[str, Any]:
        return store.get_project(project_id, require_owner(request))

    def run_access(request: Request, run_id: str) -> dict[str, Any]:
        run = store.get_run(run_id)
        project_access(request, run["project_id"])
        if request.method == "POST":
            configure_run_from_request(request, run_id)
        return workflow.present_run(run)

    def request_credentials(request: Request):
        raw = request.headers.get("x-myatom-model-config")
        if not raw:
            return None
        if len(raw) > 2048:
            raise HTTPException(status_code=422, detail="模型配置过长")
        try:
            config = json.loads(raw)
            if not isinstance(config, dict):
                raise ValueError("模型配置格式无效")
            return validate_model_credentials(config)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def configure_run_from_request(request: Request, run_id: str) -> None:
        credentials = request_credentials(request)
        if credentials is None:
            return
        if isinstance(workflow.model, ModelGateway):
            workflow.model.configure_run(run_id, credentials)

    def public_submission(message: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in message.items()
                if key not in {"idempotency_key", "request_hash", "interpreted_intents"}}

    @app.get("/api/health")
    def health():
        return {"ok": True, "model_configured": bool(settings.model_api_key), "app_env": settings.app_env}

    @app.get("/api/auth/session")
    def auth_session(request: Request):
        invited = active_invite(request)
        return {"invited": bool(invited), "platform_model_available": bool(invited and settings.model_api_key),
                "invite_required": settings.app_env == "azure_demo"}

    @app.post("/api/auth/invite")
    def accept_invite(body: InviteInput, request: Request, response: Response):
        address = request.client.host if request.client else "unknown"
        invited = invite_auth.authenticate(body.code.strip(), address)
        if not invited:
            raise HTTPException(status_code=401, detail="邀请码无效或尝试过于频繁")
        response.set_cookie(INVITE_COOKIE, invite_auth.issue(invited), httponly=True,
                            samesite="strict", secure=settings.app_env != "local", max_age=60 * 60 * 24 * 30)
        return {"invited": True, "platform_model_available": bool(settings.model_api_key),
                "invite_required": settings.app_env == "azure_demo"}

    @app.post("/api/auth/logout")
    def leave_invite(response: Response):
        response.delete_cookie(INVITE_COOKIE, httponly=True, samesite="strict", secure=settings.app_env != "local")
        return {"invited": False, "platform_model_available": False,
                "invite_required": settings.app_env == "azure_demo"}

    @app.get("/api/model/defaults")
    def model_defaults():
        return {"provider": "deepseek" if "api.deepseek.com" in settings.model_base_url else "openai_compatible",
                "base_url": settings.model_base_url,
                "model_name": settings.model_name, "api_key": ""}

    @app.post("/api/model/test")
    def test_model(request: Request):
        raw = request.headers.get("x-myatom-model-config", "")
        if not raw or len(raw) > 2048:
            raise HTTPException(status_code=422, detail="请先填写模型设置")
        try:
            config = json.loads(raw)
            credentials = validate_model_credentials(config)
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        from openai import OpenAI
        try:
            client = OpenAI(api_key=credentials.api_key, base_url=credentials.base_url, timeout=15)
            client.chat.completions.create(model=credentials.model_name,
                messages=[{"role": "user", "content": "Reply OK"}], max_tokens=8, timeout=15)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"连接失败：{type(exc).__name__}") from None
        return {"ok": True}

    @app.get("/api/projects")
    def list_projects(request: Request):
        if settings.app_env == "azure_demo" and not active_invite(request):
            return {"projects": []}
        owner = current_owner(request)
        return {"projects": store.list_projects(owner) if owner else []}

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput, request: Request, response: Response):
        if not body.title.strip():
            raise HTTPException(status_code=422, detail="请填写项目名称")
        invited = active_invite(request)
        if settings.app_env == "azure_demo" and not invited:
            raise HTTPException(status_code=401, detail="请先输入邀请码进入测试空间")
        token = request.cookies.get(COOKIE) or secrets.token_urlsafe(32)
        project = store.create_project(invite_auth.owner(invited) if invited else owner_hash(token), body.title.strip())
        if not invited:
            response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.app_env != "local", max_age=60 * 60 * 24 * 90)
        return project

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str, request: Request):
        project = project_access(request, project_id)
        project["runs"] = [workflow.present_run(run) for run in project["runs"][:1]] + project["runs"][1:]
        return project

    @app.post("/api/projects/{project_id}/runs", status_code=201)
    def create_run(project_id: str, body: RunInput, request: Request, idempotency_key: str | None = Header(default=None)):
        project_access(request, project_id)
        credentials = request_credentials(request)
        invited = active_invite(request)
        if settings.app_env == "azure_demo" and not invited:
            raise HTTPException(status_code=401, detail="请先输入邀请码进入测试空间")
        if isinstance(workflow.model, ModelGateway) and not credentials and not (invited and settings.model_api_key):
            raise HTTPException(status_code=403, detail="请在模型设置中填写自己的 API Key；邀请码测试模式可使用平台额度")
        if credentials is None and invited and isinstance(workflow.model, ModelGateway):
            try:
                workflow.model.check_platform_quota(invited)
            except RuntimeError as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from None
        if not body.request_text.strip() or len(body.request_text.strip()) < 10:
            raise HTTPException(status_code=422, detail="请至少用 10 个字描述应用需求")
        run, created = store.create_run(project_id, body.request_text.strip(), idempotency_key or str(uuid.uuid4()),
            limits={"model_calls": settings.max_model_calls, "total_tokens": settings.max_total_tokens,
                    "run_seconds": settings.max_run_seconds, "fix_rounds": settings.max_fix_rounds}, mode=body.mode)
        configure_run_from_request(request, run["id"])
        if credentials is None and invited and isinstance(workflow.model, ModelGateway):
            workflow.model.configure_platform_run(run["id"], invited)
        if created:
            workflow.enqueue(run["id"])
        return {"run": run, "created": created}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        return run_access(request, run_id)

    @app.post("/api/runs/{run_id}/model")
    def restore_run_model(run_id: str, request: Request):
        run = run_access(request, run_id)
        if (not request.headers.get("x-myatom-model-config")
                and not (active_invite(request) and store.operation_get(run_id, "platform_model_access"))):
            raise HTTPException(status_code=422, detail="请先在模型设置中填写 API Key")
        if run["status"] in {"clarifying", "planning", "building"}:
            workflow.enqueue(run_id)
        return {"ok": True}

    @app.get("/api/runs/{run_id}/messages")
    def list_messages(run_id: str, request: Request):
        run_access(request, run_id)
        return {"messages": [public_submission(item) for item in store.list_submissions(run_id)]}

    @app.get("/api/runs/{run_id}/messages/{submission_id}")
    def get_message(run_id: str, submission_id: str, request: Request):
        run_access(request, run_id)
        message = store.get_submission(submission_id)
        if message["run_id"] != run_id:
            raise NotFound("消息不存在")
        return public_submission(message)

    @app.post("/api/runs/{run_id}/messages", status_code=202)
    def submit_message(run_id: str, body: MessageInput, request: Request, idempotency_key: str | None = Header(default=None)):
        run = run_access(request, run_id)
        try:
            uuid.UUID(body.submission_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="消息编号必须是 UUID") from exc
        content = body.text
        if not content.strip() and not body.answers:
            raise HTTPException(status_code=422, detail="请输入消息或选择澄清卡答案")
        if len(body.answers) > 3 or any(len(key) > 40 or len(value) > 500 for key, value in body.answers.items()):
            raise HTTPException(status_code=422, detail="澄清答案格式无效")
        try:
            duplicate = store.get_submission(body.submission_id)
        except NotFound:
            duplicate = None
        if duplicate:
            if duplicate["run_id"] != run_id:
                raise Conflict("消息编号已用于其他任务")
            if duplicate["idempotency_key"] != (idempotency_key or body.submission_id):
                raise Conflict("消息编号与幂等键不一致")
            message, created = store.create_submission(run_id, submission_id=body.submission_id,
                key=idempotency_key or body.submission_id, card_id=body.card_ref.card_id,
                spec_version=body.card_ref.spec_version, text=content, answers=body.answers,
                reply_to_interpretation_id=body.reply_to_interpretation_id)
            return {"message": public_submission(message), "created": created}
        if body.answers:
            if run["status"] != "awaiting_clarification" or run.get("card", {}).get("type") != "clarification":
                raise HTTPException(status_code=422, detail="当前阶段不接受澄清答案")
            ids = {question["id"] for question in (run["card"].get("payload") or {}).get("questions", [])}
            if set(body.answers) - ids:
                raise HTTPException(status_code=422, detail="澄清答案包含非当前卡片的问题")
        message, created = store.create_submission(run_id, submission_id=body.submission_id,
            key=idempotency_key or body.submission_id, card_id=body.card_ref.card_id,
            spec_version=body.card_ref.spec_version, text=content, answers=body.answers,
            reply_to_interpretation_id=body.reply_to_interpretation_id)
        if created:
            messages.enqueue(message["id"])
        return {"message": public_submission(message), "created": created}

    @app.post("/api/runs/{run_id}/offer-repair")
    def offer_repair(run_id: str, request: Request):
        run_access(request, run_id)
        try:
            return workflow.offer_repair(run_id)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc

    @app.post("/api/runs/{run_id}/offer-budget")
    def offer_budget(run_id: str, request: Request):
        run_access(request, run_id)
        try:
            return workflow.offer_budget(run_id)
        except ValueError as exc:
            raise Conflict(str(exc)) from exc

    @app.post("/api/runs/{run_id}/budgets/extend", status_code=202)
    def extend_budget(run_id: str, body: BudgetExtensionInput, request: Request,
                      idempotency_key: str | None = Header(default=None)):
        run_access(request, run_id)
        selected = {kind: getattr(body, kind) for kind in
                    ("model_calls", "total_tokens", "run_seconds", "fix_rounds")}
        try:
            decision, created = store.extend_budget(run_id, key=idempotency_key or str(uuid.uuid4()),
                card_id=body.card_id, spec_version=body.spec_version, selected=selected)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if created:
            workflow.enqueue(run_id)
        return {"decision_id": decision["id"], "created": created, "run": workflow.present_run(store.get_run(run_id))}

    @app.get("/api/runs/{run_id}/events")
    def get_events(run_id: str, request: Request, after_seq: int = 0):
        run_access(request, run_id)
        return {"events": store.events(run_id, max(0, after_seq))}

    @app.get("/api/runs/{run_id}/stream")
    async def stream_events(run_id: str, request: Request, after_seq: int = 0):
        run_access(request, run_id)
        try:
            last_id = int(request.headers.get("last-event-id", "0"))
        except ValueError:
            last_id = 0
        cursor = max(0, after_seq, last_id)

        async def event_stream():
            nonlocal cursor
            idle = 0.0
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                batch = store.events(run_id, cursor)
                if batch:
                    for item in batch:
                        cursor = item["seq"]
                        yield f"id: {cursor}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                    idle = 0.0
                elif store.get_run(run_id)["status"] in {"completed", "failed", "cancelled", "budget_exceeded"}:
                    return
                await asyncio.sleep(0.25)
                idle += 0.25
                if idle >= 15:
                    yield ": heartbeat\n\n"
                    idle = 0.0

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/runs/{run_id}/build-log")
    def get_build_log(run_id: str, request: Request):
        run = run_access(request, run_id)
        try:
            content = workflow.runner.read_build_log(run["project_id"], run_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="构建日志尚未生成")
        return PlainTextResponse(content)

    @app.post("/api/runs/{run_id}/decisions", status_code=202)
    def submit_decision(run_id: str, body: DecisionInput, request: Request, idempotency_key: str | None = Header(default=None)):
        run = run_access(request, run_id)
        if run["status"] == "awaiting_repair" and body.action in {"continue_repair", "guided_repair", "rebuild", "extend_auto_repair"}:
            state = workflow.graph.get_state({"configurable": {"thread_id": run_id}}).values or {}
            blocker = workflow._recovery_blocker(state)
            if blocker:
                raise Conflict(blocker)
        payload: dict[str, Any] = {}
        if body.action == "confirm_clarification":
            duplicate = (store.get_decision_by_key(run_id, idempotency_key) if idempotency_key else None)
            card = run["card"] or {}
            answers: dict[str, str] = {}
            questions = ([{"id": question_id, "text": question_id, "required": True}
                          for question_id in duplicate["payload"]["answers"]]
                         if duplicate and duplicate["action"] == "confirm_clarification" else
                         (card.get("payload") or {}).get("questions", []))
            for question in questions:
                if question["id"] not in (body.answers or {}):
                    raise HTTPException(status_code=422, detail=f"请明确回答或采用建议：{question['text']}")
                answer = (body.answers or {})[question["id"]].strip()
                if question.get("required") and not answer:
                    raise HTTPException(status_code=422, detail=f"请回答：{question['text']}")
                answers[question["id"]] = answer[:500]
            payload = {"answers": answers}
        elif body.action == "revise_clarification":
            if not body.request_text or not 10 <= len(body.request_text.strip()) <= 5000:
                raise HTTPException(status_code=422, detail="请用 10–5000 字写明修改后的需求")
            payload = {"request_text": body.request_text.strip()}
        elif body.action == "revise_plan":
            if not (body.feedback or "").strip():
                raise HTTPException(status_code=422, detail="请写明希望修改的计划内容")
            payload = {"feedback": body.feedback.strip()[:2000]}
        elif body.action == "guided_repair":
            feedback = (body.feedback or "").strip()
            if not 3 <= len(feedback) <= 2000:
                raise HTTPException(status_code=422, detail="请用 3–2000 字说明修复方向")
            payload = {"feedback": feedback}
        elif body.action in {"continue_repair", "rebuild", "extend_auto_repair"}:
            payload = {}
        elif body.action != "approve_plan":
            raise HTTPException(status_code=422, detail="不支持的决策动作")
        decision, created = store.submit_decision(run_id, key=idempotency_key or str(uuid.uuid4()), card_id=body.card_id,
                                                   spec_version=body.spec_version, action=body.action, payload=payload)
        if created:
            workflow.enqueue(run_id)
        return {"decision_id": decision["id"], "created": created, "run": store.get_run(run_id)}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: str, request: Request):
        run = run_access(request, run_id)
        if run["status"] in {"completed", "failed", "cancelled", "budget_exceeded"}:
            return run
        if run["status"] in {"awaiting_clarification", "awaiting_plan", "awaiting_repair", "awaiting_budget"}:
            return store.update_run(run_id, status="cancelled", phase="Cancelled", cancel_requested=1,
                                    event_type="cancelled", event_payload={})
        return store.update_run(run_id, cancel_requested=1, event_type="cancel_requested", event_payload={})

    @app.get("/api/versions/{version_id}")
    def get_version(version_id: str, request: Request):
        version = store.get_version(version_id)
        project_access(request, version["project_id"])
        return version

    @app.post("/api/projects/{project_id}/versions/{version_id}/activate")
    def activate_version(project_id: str, version_id: str, request: Request):
        project_access(request, project_id)
        version = store.activate_version(project_id, version_id)
        return {"version": version, "active_version_id": version["id"]}

    @app.get("/api/versions/{version_id}/preview")
    def get_preview(version_id: str, request: Request):
        version = store.get_version(version_id)
        project_access(request, version["project_id"])
        if settings.app_env not in {"local", "azure_demo"}:
            raise HTTPException(status_code=503, detail="当前环境尚无预览服务")
        try:
            store.get_version_file(version_id, "dist/index.html")
        except NotFound:
            raise HTTPException(status_code=404, detail="该版本尚无可预览的构建产物")
        ticket, expires = preview_access.issue_ticket(version_id, version["project_id"])
        return {"url": f"{settings.workbench_origin.rstrip('/')}/preview/open/{version_id}?ticket={ticket}", "expires_at": expires,
                "scope": "trusted_azure_demo" if settings.app_env == "azure_demo" else "local_preview_only"}

    @app.get("/api/versions/{version_id}/files/{name:path}")
    def get_file(version_id: str, name: str, request: Request):
        version = store.get_version(version_id)
        project_access(request, version["project_id"])
        try:
            content, _ = store.get_version_file(version_id, name)
        except NotFound:
            raise HTTPException(status_code=404, detail="文件不存在")
        return PlainTextResponse(content)

    if settings.app_env in {"local", "azure_demo"}:
        from .preview import create_preview_app
        app.mount("/preview", create_preview_app(settings), name="preview")

    dist = settings.root / "web" / "dist"
    if dist.exists():
        @app.get("/projects/{project_id}", include_in_schema=False)
        def project_page(project_id: str):
            return FileResponse(dist / "index.html")

        @app.get("/projects/{project_id}/{view}", include_in_schema=False)
        def project_view_page(project_id: str, view: str):
            if view not in {"overview", "docs", "tests", "versions", "publish"}:
                raise HTTPException(status_code=404, detail="页面不存在")
            return FileResponse(dist / "index.html")

        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


app = create_app() if Settings().app_env != "azure_demo" else None
