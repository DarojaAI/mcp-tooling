"""Tests for runtime.base"""

import pytest

from runtime.base import BaseTool


class ExampleTool(BaseTool):
    """Example tool for testing."""
    
    @property
    def tool_name(self) -> str:
        return "example_tool"
    
    @property
    def description(self) -> str:
        return "An example tool for testing"
    
    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "count": {"type": "integer", "default": 1},
            },
            "required": ["message"],
        }
    
    async def call(self, args: dict) -> dict:
        message = args["message"]
        count = args.get("count", 1)
        return {"result": f"{message} x {count}"}


def test_tool_name():
    """Test tool_name property."""
    tool = ExampleTool()
    assert tool.tool_name == "example_tool"


def test_description():
    """Test description property."""
    tool = ExampleTool()
    assert tool.description == "An example tool for testing"


def test_input_schema():
    """Test input_schema property."""
    tool = ExampleTool()
    schema = tool.input_schema
    assert schema["type"] == "object"
    assert "message" in schema["required"]


@pytest.mark.asyncio
async def test_call():
    """Test tool call."""
    tool = ExampleTool()
    result = await tool.call({"message": "hello", "count": 3})
    assert result == {"result": "hello x 3"}


@pytest.mark.asyncio
async def test_call_with_defaults():
    """Test tool call with default values."""
    tool = ExampleTool()
    result = await tool.call({"message": "hello"})
    assert result == {"result": "hello x 1"}


def test_to_mcp_tool_definition():
    """Test MCP tool definition format."""
    tool = ExampleTool()
    definition = tool.to_mcp_tool_definition()
    
    assert definition["name"] == "example_tool"
    assert definition["description"] == "An example tool for testing"
    assert definition["inputSchema"]["type"] == "object"
