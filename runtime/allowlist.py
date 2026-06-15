"""
Allowlist enforcement for MCP tools.

Provides two layers of filtering:
1. Tool name allowlist - which tools can be called
2. Caller token allowlist - which callers can invoke tools
"""

import os


class Allowlist:
    """
    Allowlist for tool names and caller tokens.
    
    Usage:
        # Allow all tools, restrict callers
        allowlist = Allowlist(
            allow_all_tools=True,
            allowed_tokens={"secret-token-1", "secret-token-2"}
        )
        
        # Restrict both tools and callers
        allowlist = Allowlist(
            allowed_tools={"search_flights", "get_offer"},
            allowed_tokens={"secret-token-1"}
        )
    """
    
    def __init__(
        self,
        allowed_tools: set[str] | None = None,
        allowed_tokens: set[str] | None = None,
        allow_all_tools: bool = False,
        allow_all_callers: bool = False,
    ) -> None:
        """
        Initialize allowlist.
        
        Args:
            allowed_tools: Set of allowed tool names (if None and allow_all_tools=False, no tools allowed)
            allowed_tokens: Set of allowed bearer tokens (if None and allow_all_callers=False, no callers allowed)
            allow_all_tools: If True, all tools are allowed (overrides allowed_tools)
            allow_all_callers: If True, all callers are allowed (overrides allowed_tokens)
        """
        self.allowed_tools = allowed_tools or set()
        self.allowed_tokens = allowed_tokens or set()
        self.allow_all_tools = allow_all_tools
        self.allow_all_callers = allow_all_callers
    
    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool name is allowed."""
        if self.allow_all_tools:
            return True
        return tool_name in self.allowed_tools
    
    def is_caller_allowed(self, token: str | None) -> bool:
        """Check if a caller token is allowed."""
        if self.allow_all_callers:
            return True
        if token is None:
            return False
        return token in self.allowed_tokens
    
    @classmethod
    def from_env(cls) -> "Allowlist":
        """
        Create allowlist from environment variables.
        
        Env vars:
            MCPTOOLING_ALLOWED_TOOLS: Comma-separated tool names (empty = allow all)
            MCPTOOLING_ALLOWED_TOKENS: Comma-separated bearer tokens (required)
        
        Returns:
            Allowlist instance
        
        Raises:
            ValueError: If MCPTOOLING_ALLOWED_TOKENS is not set
        """
        tools_str = os.getenv("MCPTOOLING_ALLOWED_TOOLS", "")
        tokens_str = os.getenv("MCPTOOLING_ALLOWED_TOKENS", "")
        
        if not tokens_str:
            raise ValueError(
                "MCPTOOLING_ALLOWED_TOKENS environment variable is required "
                "(comma-separated bearer tokens)"
            )
        
        # Parse tools (empty = allow all)
        if tools_str:
            allowed_tools = set(t.strip() for t in tools_str.split(",") if t.strip())
            allow_all_tools = False
        else:
            allowed_tools = set()
            allow_all_tools = True
        
        # Parse tokens
        allowed_tokens = set(t.strip() for t in tokens_str.split(",") if t.strip())
        
        return cls(
            allowed_tools=allowed_tools,
            allowed_tokens=allowed_tokens,
            allow_all_tools=allow_all_tools,
            allow_all_callers=False,
        )
