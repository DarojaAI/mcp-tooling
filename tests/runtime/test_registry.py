"""Tests for runtime.registry"""

import pytest
from runtime.registry import ToolRegistry
from runtime.base import BaseTool


class MockTool(BaseTool):
    """Mock tool for testing."""
    
    def __init__(self, name: str = "mock_tool"):
        self._name = name
    
    @property
    def tool_name(self) -> str:
        return self._name
    
    @property
    def description(self) -> str:
        return f"Mock tool: {self._name}"
    
    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "value": {"type": "string"},
            },
            "required": ["value"],
        }
    
    async def call(self, args: dict) -> dict:
        return {"result": f"Called {self._name} with {args['value']}"}


def test_register_tool():
    """Test registering a tool."""
    registry = ToolRegistry()
    tool = MockTool("test_tool")
    
    registry.register(tool)
    assert len(registry) == 1
    assert registry.get_tool("test_tool") == tool


def test_register_duplicate_tool():
    """Test that registering duplicate tool name raises ValueError."""
    registry = ToolRegistry()
    tool1 = MockTool("duplicate")
    tool2 = MockTool("duplicate")
    
    registry.register(tool1)
    
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool2)


def test_list_tools():
    """Test listing all tools."""
    registry = ToolRegistry()
    tool1 = MockTool("tool1")
    tool2 = MockTool("tool2")
    
    registry.register(tool1)
    registry.register(tool2)
    
    tools = registry.list_tools()
    assert len(tools) == 2
    assert any(t["name"] == "tool1" for t in tools)
    assert any(t["name"] == "tool2" for t in tools)


def test_get_tool():
    """Test getting a tool by name."""
    registry = ToolRegistry()
    tool = MockTool("my_tool")
    
    registry.register(tool)
    
    retrieved = registry.get_tool("my_tool")
    assert retrieved == tool
    
    not_found = registry.get_tool("nonexistent")
    assert not_found is None


@pytest.mark.asyncio
async def test_call_tool():
    """Test calling a tool."""
    registry = ToolRegistry()
    tool = MockTool("test_call")
    
    registry.register(tool)
    
    result = await registry.call("test_call", {"value": "hello"})
    assert result == {"result": "Called test_call with hello"}


@pytest.mark.asyncio
async def test_call_nonexistent_tool():
    """Test calling a nonexistent tool raises ValueError."""
    registry = ToolRegistry()
    
    with pytest.raises(ValueError, match="not found"):
        await registry.call("nonexistent", {})


@pytest.mark.asyncio
async def test_call_with_invalid_args():
    """Test calling with invalid arguments raises ValueError."""
    registry = ToolRegistry()
    tool = MockTool("validation_test")
    
    registry.register(tool)
    
    # Missing required 'value' field
    with pytest.raises(ValueError, match="Invalid arguments"):
        await registry.call("validation_test", {})


@pytest.mark.asyncio
async def test_call_with_extra_args():
    """Test calling with extra arguments (should pass validation)."""
    registry = ToolRegistry()
    tool = MockTool("extra_test")
    
    registry.register(tool)
    
    # Extra field 'extra' should be allowed (JSON Schema default behavior)
    result = await registry.call("extra_test", {"value": "hello", "extra": "ignored"})
    assert "result" in result
