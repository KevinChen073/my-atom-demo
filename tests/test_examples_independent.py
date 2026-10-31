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
from backend.preview import create_preview_app
from backend.settings import Settings
from tests.test_mvp1 import wait_status


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "examples" / "catalog.json"


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
        assert example["smoke"]["requires_server_data"] is True
        request = example["request_text"]
        assert "React" in request and "Vite" in request and "appData" in request
        assert "服务端" in request and "刷新" in request
        assert "不用浏览器存储" in request and "不用浏览器存储、外部接口或图片" in request


def test_example_prompts_include_observable_short_smoke_paths():
    examples = {item["id"]: item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["examples"]}
    pomodoro = examples["pomodoro_todo"]["request_text"]
    for phrase in ("新增任务", "勾选完成", "10 秒演示", "暂停", "继续", "重置", "只为当前任务增加一次番茄数"):
        assert phrase in pomodoro
    game = examples["elder_clicker"]["request_text"]
    for phrase in ("至少有三款", "切换皮肤", "10 秒演示", "点击角色每次加 1 分", "最高分", "选中皮肤", "键盘", "回合结束时按最终本轮分数只结算保存一次最高分", "快速连续点击不得漏分"):
        assert phrase in game
    ordering = examples["mobile_ordering"]["request_text"]
    for phrase in ("Web/H5", "不是原生微信小程序", "购物车", "取餐姓名", "orders", "订单历史", "375 和 390"):
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


SCENARIOS = {
    "pomodoro_todo": {
        "entity": {"name": "todos", "fields": [
            {"name": "title", "type": "text", "required": True},
            {"name": "completed", "type": "boolean", "required": True},
            {"name": "pomodoros", "type": "number", "required": True},
        ]},
        "data": {"title": "固定源码烟测", "completed": False, "pomodoros": 0},
    },
    "elder_clicker": {
        "entity": {"name": "game_state", "fields": [
            {"name": "skin", "type": "text", "required": True},
            {"name": "high_score", "type": "number", "required": True},
        ]},
        "data": {"skin": "田园爷爷", "high_score": 3},
    },
    "mobile_ordering": {
        "entity": {"name": "orders", "fields": [
            {"name": "customer_name", "type": "text", "required": True},
            {"name": "items", "type": "text", "required": True},
            {"name": "total", "type": "number", "required": True},
            {"name": "status", "type": "text", "required": True},
        ]},
        "data": {"customer_name": "测试顾客", "items": "红茶×1", "total": 12, "status": "已提交"},
    },
}


class FixedExampleModel:
    """Only exercises workflow/build/data plumbing; it does not assess model output quality."""

    def __init__(self, example_id: str, title: str):
        self.example_id = example_id
        self.title = title

    def check_limits(self, run_id: str) -> None:
        return None

    def generate(self, run_id: str, node: str, cache_key: str, system: str, user: str, *, max_tokens: int = 4000):
        scenario = SCENARIOS[self.example_id]
        entity = scenario["entity"]
        if node == "clarify":
            return {"summary": self.title, "assumptions": ["固定 Web 模板"], "questions": []}
        if node == "plan":
            return {"title": self.title, "pages": [{"name": "首页", "purpose": self.title}],
                    "features": ["交互与服务端记录"], "data_model": [entity["name"]],
                    "acceptance": ["记录刷新后可读取"], "tasks": ["构建示例"], "limitations": [],
                    "entities": [entity]}
        if node == "code_loop":
            source = f"""import {{ useEffect, useState }} from 'react'
import {{ listRecords, createRecord, type AppRecord }} from './appData'
import './App.css'
const entity = '{entity['name']}'
const seedData: Record<string, unknown> = {json.dumps(scenario['data'], ensure_ascii=False)}
export default function App() {{
  const [rows, setRows] = useState<AppRecord[]>([])
  const [error, setError] = useState('')
  useEffect(() => {{ void listRecords(entity).then(setRows).catch(err => setError(String(err))) }}, [])
  async function add() {{ try {{ await createRecord(entity, seedData); setRows(await listRecords(entity)) }} catch (err) {{ setError(String(err)) }} }}
  return <main><h1>{self.title}</h1><button onClick={{add}}>新增记录</button><p role="alert">{{error}}</p><p>{{rows.length}} 条记录</p></main>
}}
"""
            return {"app_tsx": source, "app_css": "body { font-family: sans-serif; } main { padding: 2rem; }"}
        raise AssertionError(node)


@pytest.mark.parametrize("example_id", ["pomodoro_todo", "elder_clicker", "mobile_ordering"])
def test_example_fixed_source_workflow_build_preview_and_data(tmp_path: Path, example_id: str):
    """No paid call: prove both example schemas traverse the real build and preview APIs."""
    example = next(item for item in json.loads(CATALOG.read_text(encoding="utf-8"))["examples"] if item["id"] == example_id)
    settings = Settings(data_dir=tmp_path, model_api_key="test-only", preview_port=8001)
    app = create_app(settings, model=FixedExampleModel(example_id, example["title"]))
    with TestClient(app) as main:
        project = main.post("/api/projects", json={"title": example["title"]}).json()
        created = main.post(f"/api/projects/{project['id']}/runs", json={"request_text": example["request_text"]})
        assert created.status_code == 201, created.text
        run_id = created.json()["run"]["id"]
        clarify = wait_status(main, run_id, "awaiting_clarification")
        assert main.post(f"/api/runs/{run_id}/decisions", json={"card_id": clarify["card_id"],
                         "spec_version": clarify["spec_version"], "action": "confirm_clarification", "answers": {}}).status_code == 202
        plan = wait_status(main, run_id, "awaiting_plan")
        assert plan["plan"]["entities"] == [SCENARIOS[example_id]["entity"]]
        assert main.post(f"/api/runs/{run_id}/decisions", json={"card_id": plan["card_id"],
                         "spec_version": plan["spec_version"], "action": "approve_plan"}).status_code == 202
        done = wait_status(main, run_id, "completed", timeout=90)
        assert done["status"] == "completed", done.get("error")
        versions = main.get(f"/api/projects/{project['id']}").json()["versions"]
        assert len(versions) == 1 and versions[0]["manifest"]["build"]["ok"] is True
        version = versions[0]
        issued = main.get(f"/api/versions/{version['id']}/preview")
        assert issued.status_code == 200
        path = urlsplit(issued.json()["url"])
        with TestClient(create_preview_app(settings), base_url=f"{path.scheme}://{path.netloc}") as preview:
            opened = preview.get(path.path + "?" + path.query)
            assert opened.status_code == 200 and "assets" in opened.text
            endpoint = f"/data/{version['id']}/{SCENARIOS[example_id]['entity']['name']}"
            payload = SCENARIOS[example_id]["data"]
            saved = preview.post(endpoint, json={"data": payload}, headers={"Origin": f"{path.scheme}://{path.netloc}"})
            assert saved.status_code == 201, saved.text
            assert all(saved.json()[key] == value for key, value in payload.items())
            assert len(preview.get(endpoint).json()) == 1

