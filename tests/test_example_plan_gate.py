"""Regression checks for plan mistakes observed in paid example smoke runs."""

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
        "data_model": [],
        "acceptance": acceptance,
        "tasks": [],
        "limitations": ["演示回合不计入最高分"] if bad_demo_limit else [],
        "entities": [{"name": "game_profile", "fields": [
            {"name": "high_score", "type": "number", "required": True},
            {"name": "selected_skin", "type": "text", "required": True},
        ]}],
    }


def test_game_plan_rejects_demo_exception_and_missing_final_settlement():
    assert plan_gaps("elder_clicker", game_plan()) == []
    assert "计划与演示回合最高分要求冲突" in plan_gaps("elder_clicker", game_plan(bad_demo_limit=True))
    assert "回合结束按最终本轮得分结算最高分，避免快速连点漏分" in plan_gaps(
        "elder_clicker", game_plan(omit_settlement=True)
    )


def test_order_plan_requires_persisted_orders_entity():
    plan = {"features": ["菜单、购物车、提交订单"], "data_model": [], "acceptance": ["刷新后保留订单"],
            "tasks": [], "entities": [{"name": "cart", "fields": [{"name": "total", "type": "number"}]}]}
    assert "缺少 orders 订单实体" in plan_gaps("mobile_ordering", plan)
