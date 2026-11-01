"""Regression checks for plan mistakes observed in paid example smoke runs."""

import pytest

from backend.exceptions import PlanValidationError, classify
from backend.workflow import normalize_plan
from tests.live_examples_smoke import plan_gaps


def game_plan(*, bad_demo_limit: bool = False, omit_settlement: bool = False) -> dict:
    acceptance = [
        "点击角色加分且三套皮肤可切换",
        "10 秒演示回合也计入统一最高分",
    ]
    if not omit_settlement:
        acceptance.append("回合结束时按最终得分只保存一次最高分，快速连点不漏分")
    return {
        "features": ["点击角色计分，皮肤切换"],
        "data_model": ["localStorage 保存最高分、皮肤"],
        "acceptance": acceptance,
        "tasks": [],
        "limitations": ["演示回合不计入最高分"] if bad_demo_limit else [],
    }


def test_game_plan_rejects_demo_exception_and_missing_final_settlement():
    assert plan_gaps("elder_clicker", game_plan()) == []
    assert "计划与演示回合最高分要求冲突" in plan_gaps("elder_clicker", game_plan(bad_demo_limit=True))
    assert "回合结束按最终本轮得分结算最高分，避免快速连点漏分" in plan_gaps(
        "elder_clicker", game_plan(omit_settlement=True)
    )


def test_order_plan_requires_local_order_history():
    plan = {"features": ["菜单、购物车、提交"], "data_model": ["localStorage 保存购物车"],
            "acceptance": ["刷新后保留记录"], "tasks": []}
    assert "缺少本地订单历史" in plan_gaps("mobile_ordering", plan)


def test_plan_keeps_refresh_acceptance_after_eight_items_and_allows_negated_server_storage():
    raw = {"title": "点击游戏", "features": ["点击角色计分"],
           "data_model": ["localStorage 保存最高分和皮肤"],
           "acceptance": [f"操作验收 {number}" for number in range(8)] + ["刷新页面后读回最高分和皮肤"],
           "tasks": ["生成应用"], "limitations": ["不涉及服务端存储，业务数据仅在 localStorage"]}
    plan = normalize_plan(raw)
    assert plan["acceptance"][-1] == "刷新页面后读回最高分和皮肤"
    assert len(plan["acceptance"]) == 9
    assert classify(PlanValidationError("missing_refresh_check")) == ("plan_validation_failed", "PlanValidationError")
    raw["limitations"] = ["不支持服务端业务 CRUD、SQL、缓存、外部接口或第三方库"]
    normalize_plan(raw)
    raw["limitations"] = ["需要服务端存储最高分"]
    with pytest.raises(ValueError, match="localStorage"):
        normalize_plan(raw)
