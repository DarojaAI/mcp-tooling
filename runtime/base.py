"""
Base tool interface for MCP servers.

The BaseTool shape mirrors dev-nexus's BaseSkill interface:
- tool_name ↔ skill_id
- input_schema ↔ parameters (JSON Schema)
- call() ↔ execute()

This intentional alignment means dev-nexus skills can be adapted to MCP tools
with minimal glue code (see Phase 7 plan).
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """
    Base class for all MCP tools.
    
    Subclasses must implement:
    - tool_name: Unique identifier for this tool
    - description: Human-readable description
    - input_schema: JSON Schema dict for input validation
    - call(args): Execute the tool with validated arguments
    """
    
    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Unique tool identifier (e.g., 'search_flights')."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this tool does."""
        pass
    
    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """
        JSON Schema for input validation.
        
        Example:
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            }
        """
        pass
    
    @abstractmethod
    async def call(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        Execute the tool with the given arguments.
        
        Args:
            args: Validated input arguments (already validated against input_schema)
        
        Returns:
            Result dict. Convention: {"result": ...} for success, {"error": ..., "details": ...} for errors.
        
        Raises:
            Should return error dicts instead of raising exceptions when possible
            (exceptions leak stack traces to callers).
        """
        pass
    
    def to_mcp_tool_definition(self) -> dict[str, Any]:
        """Convert to MCP tools/list format."""
        return {
            "name": self.tool_name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
