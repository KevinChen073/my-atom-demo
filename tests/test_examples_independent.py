"""No-model contract checks for the curated example catalog."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.settings import Settings
from tests.live_examples_smoke import version_hooks_use_local_storage
from tests.test_mvp1 import wait_status


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples" / "catalog.json"


def test_live_example_smoke_checks_all_hooks_for_storage():
    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    class Client:
        def get(self, path):
            return Response("window.localStorage.setItem('orders', '[]')" if path.endswith("useOrders.ts") else "")

    version = {"id": "v1", "manifest": {"files": [
        {"path": "src/hooks/useAppState.ts"}, {"path": "src/hooks/useOrders.ts"},
        {"path": "src/App.tsx"},
    ]}}
    assert version_hooks_use_local_storage(Client(), version)


def test_active_example_catalog_is_complete_and_unique():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    assert catalog["schema_version"] == 1
    examples = catalog["examples"]
    assert isinstance(examples, list) and len(examples) == 3
    ids = [example["id"] for example in examples]
    assert len(ids) == len(set(ids))
    assert set(ids) == {"pomodoro_todo", "elder_clicker", "mobile_ordering"}
    for example in examples:
        assert example["title"].strip()
        assert example["description"].strip()
        assert 20 <= len(example["request_text"]) <= 5000
        assert example["smoke"]["checks"]
        assert example["smoke"]["requires_local_storage"] is True
        assert "requires_server_data" not in example["smoke"]
        request = example["request_text"]
        assert "React" in request and "Vite" in request and "localStorage" in request
        assert "刷新" in request
        assert "不用服务端业务接口" in request


def test_example_prompts_include_observable_short_smoke_paths():
    examples = {item["id"]: item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["examples"]}
    pomodoro = examples["pomodoro_todo"]["request_text"]
    for phrase in ("新增任务", "勾选完成", "10 秒演示", "暂停", "继续", "重置", "只为当前任务增加一次番茄数"):
        assert phrase in pomodoro
    game = examples["elder_clicker"]["request_text"]
    for phrase in ("至少有三款", "切换皮肤", "10 秒演示", "点击角色每次加 1 分", "最高分", "选中皮肤", "键盘", "回合结束时按最终本轮分数只结算保存一次最高分", "快速连续点击不得漏分"):
        assert phrase in game
    ordering = examples["mobile_ordering"]["request_text"]
    for phrase in ("Web/H5", "不是原生微信小程序", "购物车", "取餐姓名", "订单", "订单历史", "375 和 390"):
        assert phrase in ordering


def test_built_homepage_includes_active_catalog_without_model_call(tmp_path: Path):
    """Check that the actual served home bundle carries the curated cards and drafts."""
    npm = shutil.which("npm")
    assert npm, "Node/npm is required for the Web template"
    build = subprocess.run([npm, "run", "build"], cwd=ROOT / "web", capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
    assert build.returncode == 0, build.stdout + build.stderr

    class NoCallModel:
        def generate(self, *args, **kwargs):
            raise AssertionError("Opening the homepage must not call a model")

    settings = Settings(data_dir=tmp_path, model_api_key="test-only")
    with TestClient(create_app(settings, model=NoCallModel())) as client:
        page = client.get("/")
        assert page.status_code == 200
        asset = re.search(r'src="([^"]+\.js)"', page.text)
        assert asset, page.text
        bundle = client.get(asset.group(1))
        assert bundle.status_code == 200
        for example in json.loads(CATALOG.read_text(encoding="utf-8"))["examples"]:
            assert example["title"] in bundle.text
            assert example["request_text"][:30] in bundle.text


class FixedExampleModel:
    """Deterministic source for workflow and preview plumbing, not example quality."""

    def __init__(self, title: str):
        self.title = title

    def check_limits(self, run_id: str) -> None:
        pass

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000):
        if node == "clarify":
            return {"summary": self.title, "questions": [{"text": "是否只在本机浏览器保存？", "default": "是", "required": True}]}
        if node == "clarity_gate":
            return {"complete": True, "missing": []}
        if node == "plan":
            return {"title": self.title, "pages": [{"name": "首页", "purpose": self.title}],
                    "features": ["保存本地记录"], "data_model": ["localStorage 记录"],
                    "acceptance": ["刷新后可读取"], "tasks": ["构建示例"], "limitations": []}
        if node == "code_loop":
            return {"files": {
                "src/App.tsx": "import './app.css'\nimport { useAppState } from './hooks/useAppState'\nexport default function App() { const { count, add, error } = useAppState(); return <main><h1>" + self.title + "</h1><button onClick={add}>新增记录</button><p role=\"alert\">{error}</p><p>{count} 条记录</p></main> }",
                "src/hooks/useAppState.ts": "import { useState } from 'react'\nimport { generatedAppStorage } from './generatedAppStorage'\nexport function useAppState() { const [count, setCount] = useState(() => { try { return Number(generatedAppStorage.getItem('count') || '0') } catch { return 0 } }); const [error, setError] = useState(''); function add() { try { const next = count + 1; generatedAppStorage.setItem('count', String(next)); setCount(next) } catch { setError('本地保存失败') } } return { count, add, error } }",
                "src/app.css": "body { font-family: sans-serif; } main { padding: 2rem; }",
                "readme.md": "# " + self.title + "\n记录通过项目存储适配器保存在当前浏览器的 localStorage。",
            }}
        raise AssertionError(node)


@pytest.mark.parametrize("example_id", ["pomodoro_todo", "elder_clicker", "mobile_ordering"])
def test_example_fixed_source_workflow_build_preview_and_data(tmp_path: Path, example_id: str):
    example = next(item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["examples"] if item["id"] == example_id)
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", preview_port=8001)
    app = create_app(settings, model=FixedExampleModel(example["title"]))
    with TestClient(app) as main:
        project = main.post("/api/projects", json={"title": example["title"]}).json()
        created = main.post(f"/api/projects/{project['id']}/runs", json={"request_text": example["request_text"]})
        assert created.status_code == 201, created.text
        run_id = created.json()["run"]["id"]
        clarify = wait_status(main, run_id, "awaiting_clarification")
        assert main.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarify["card_id"],
                         "spec_version": clarify["spec_version"], "action": "confirm_clarification", "answers": {"q1": "是"}}).status_code == 202
        plan = wait_status(main, run_id, "awaiting_plan")
        assert plan["plan"]["entities"] == []
        assert main.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
                         "spec_version": plan["spec_version"], "action": "approve_plan"}).status_code == 202
        done = wait_status(main, run_id, "completed", timeout=90)
        version = main.get(f"/api/projects/{project['id']}").json()["versions"][0]
        assert done["version_id"] == version["id"]
        assert version["manifest"]["preview"]["ok"] is True
        hook = main.get(f"/api/versions/{version['id']}/files/src/hooks/useAppState.ts")
        assert hook.status_code == 200 and "generatedAppStorage.setItem" in hook.text
        issued = main.get(f"/api/versions/{version['id']}/preview")
        assert issued.status_code == 200
        path = urlsplit(issued.json()["url"])
        assert path.netloc == urlsplit(settings.workbench_origin).netloc
        opened = main.get(issued.json()["url"], follow_redirects=False)
        assert opened.status_code == 303
        preview = main.get(opened.headers["location"])
        assert preview.status_code == 200 and "assets" in preview.text
        assert f'content="{project["id"].replace("-", "")}"' in preview.text
        assert main.get(f"/data/{version['id']}/todos").status_code == 404
