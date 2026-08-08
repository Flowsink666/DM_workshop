import asyncio
import inspect

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import dm_workshop.mcp_server as mcp_server
from dm_workshop.mcp_server import create_shop, define_item, learn_spell, mcp


def test_expected_mcp_tools_are_registered():
    names = set(mcp._tool_manager._tools)
    assert names == {
        "list_capability_groups", "list_group_actions", "call_capability",
    }
    assert len(mcp_server._implementation_mcp._tool_manager._tools) == 42


def test_capability_groups_cover_internal_tools_exactly_once():
    groups = mcp_server.list_capability_groups()
    assert [group["id"] for group in groups] == [
        "campaign", "actors", "inventory", "magic",
        "commerce", "encounter", "dice",
    ]

    actions = []
    for group in groups:
        listed = mcp_server.list_group_actions(group["id"])["actions"]
        assert len(listed) == group["action_count"]
        assert all(set(action) == {"name", "description", "mutating"}
                   for action in listed)
        actions.extend(action["name"] for action in listed)

    internal = set(mcp_server._implementation_mcp._tool_manager._tools)
    assert len(actions) == len(set(actions)) == 42
    assert set(actions) == internal


def test_capability_router_rejects_unknown_or_cross_group_actions():
    with pytest.raises(ToolError, match="未知 MCP 功能大类"):
        asyncio.run(mcp.call_tool(
            "call_capability",
            {"group": "unknown", "action": "list_campaigns", "arguments": {}},
        ))
    with pytest.raises(ToolError, match="不属于 MCP 功能大类"):
        asyncio.run(mcp.call_tool(
            "call_capability",
            {"group": "dice", "action": "list_campaigns", "arguments": {}},
        ))


def test_capability_router_reuses_original_argument_validation():
    with pytest.raises(ToolError, match="campaign_id"):
        asyncio.run(mcp_server.call_capability(
            "campaign", "get_campaign_summary", {}
        ))


def test_money_tool_parameters_only_use_gp():
    define_parameters = set(inspect.signature(define_item).parameters)
    shop_parameters = set(inspect.signature(create_shop).parameters)
    assert "price_gp" in define_parameters
    assert "price_cp" not in define_parameters
    assert "wallet_gp" in shop_parameters
    assert "wallet_cp" not in shop_parameters


def test_learn_spell_preserves_legacy_remove_parameter_position():
    parameters = list(inspect.signature(learn_spell).parameters)
    assert parameters[:4] == [
        "campaign_id", "actor_id", "spell_id", "remove",
    ]
