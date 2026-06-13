"""
Tool registry for MCP servers.

Manages tool registration, listing, validation, and dispatch.
"""

import jsonschema
from typing import Any
from runtime.base import BaseTool


class ToolRegistry:
    """
    Central registry for MCP tools.
    
    Usage:
        registry = ToolRegistry()
        registry.register(SearchFlightsTool())
        registry.register(BookFlightTool())
        
        # List all tools (MCP tools/list format)
        tools = registry.list_tools()
        
        # Call a tool
        result = await registry.call("search_flights", {"origin": "JFK", "destination": "SFO"})
    """
    
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
    
    def register(self, tool: BaseTool) -> None:
        """
        Register a tool.
        
        Args:
            tool: BaseTool instance
        
        Raises:
            ValueError: If a tool with this name is already registered
        """
        if tool.tool_name in self._tools:
            raise ValueError(f"Tool '{tool.tool_name}' is already registered")
        
        self._tools[tool.tool_name] = tool
    
    def list_tools(self) -> list[dict[str, Any]]:
        """
        List all registered tools in MCP tools/list format.
        
        Returns:
            List of tool definitions: [{"name": ..., "description": ..., "inputSchema": ...}, ...]
        """
        return [tool.to_mcp_tool_definition() for tool in self._tools.values()]
    
    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name. Returns None if not found."""
        return self._tools.get(name)
    
    async def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Call a tool by name with the given arguments.
        
        Args:
            name: Tool name
            args: Input arguments (will be validated against input_schema)
        
        Returns:
            Tool result dict
        
        Raises:
            ValueError: If tool not found or validation fails
        """
        tool = self.get_tool(name)
        if tool is None:
            raise ValueError(f"Tool '{name}' not found")
        
        # Validate args against input_schema
        try:
            jsonschema.validate(instance=args, schema=tool.input_schema)
        except jsonschema.ValidationError as e:
            raise ValueError(f"Invalid arguments for tool '{name}': {e.message}") from e
        
        # Call the tool
        return await tool.call(args)
    
    def __len__(self) -> int:
        """Number of registered tools."""
        return len(self._tools)
