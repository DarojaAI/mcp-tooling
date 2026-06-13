"""Tests for runtime.allowlist"""

import pytest

from runtime.allowlist import Allowlist


def test_tool_allowlist():
    """Test tool name allowlist."""
    allowlist = Allowlist(allowed_tools={"tool1", "tool2"})
    
    assert allowlist.is_tool_allowed("tool1")
    assert allowlist.is_tool_allowed("tool2")
    assert not allowlist.is_tool_allowed("tool3")


def test_caller_allowlist():
    """Test caller token allowlist."""
    allowlist = Allowlist(allowed_tokens={"token1", "token2"})
    
    assert allowlist.is_caller_allowed("token1")
    assert allowlist.is_caller_allowed("token2")
    assert not allowlist.is_caller_allowed("token3")
    assert not allowlist.is_caller_allowed(None)


def test_allow_all_tools():
    """Test allow_all_tools flag."""
    allowlist = Allowlist(allow_all_tools=True, allowed_tokens={"token1"})
    
    assert allowlist.is_tool_allowed("any_tool")
    assert allowlist.is_tool_allowed("another_tool")


def test_allow_all_callers():
    """Test allow_all_callers flag."""
    allowlist = Allowlist(allowed_tools={"tool1"}, allow_all_callers=True)
    
    assert allowlist.is_caller_allowed("any_token")
    assert allowlist.is_caller_allowed(None)


def test_from_env_with_tools_and_tokens(monkeypatch):
    """Test creating allowlist from environment variables."""
    monkeypatch.setenv("MCPTOOLING_ALLOWED_TOOLS", "tool1,tool2,tool3")
    monkeypatch.setenv("MCPTOOLING_ALLOWED_TOKENS", "token1,token2")
    
    allowlist = Allowlist.from_env()
    
    assert allowlist.is_tool_allowed("tool1")
    assert allowlist.is_tool_allowed("tool2")
    assert not allowlist.is_tool_allowed("tool4")
    assert allowlist.is_caller_allowed("token1")
    assert not allowlist.is_caller_allowed("token3")


def test_from_env_empty_tools_means_allow_all(monkeypatch):
    """Test that empty MCPTOOLING_ALLOWED_TOOLS means allow all tools."""
    monkeypatch.setenv("MCPTOOLING_ALLOWED_TOOLS", "")
    monkeypatch.setenv("MCPTOOLING_ALLOWED_TOKENS", "token1")
    
    allowlist = Allowlist.from_env()
    
    assert allowlist.is_tool_allowed("any_tool")
    assert allowlist.allow_all_tools


def test_from_env_missing_tokens_raises(monkeypatch):
    """Test that missing MCPTOOLING_ALLOWED_TOKENS raises ValueError."""
    monkeypatch.delenv("MCPTOOLING_ALLOWED_TOKENS", raising=False)
    
    with pytest.raises(ValueError, match="MCPTOOLING_ALLOWED_TOKENS"):
        Allowlist.from_env()


def test_from_env_whitespace_handling(monkeypatch):
    """Test that whitespace is stripped from env vars."""
    monkeypatch.setenv("MCPTOOLING_ALLOWED_TOOLS", " tool1 , tool2 , ")
    monkeypatch.setenv("MCPTOOLING_ALLOWED_TOKENS", " token1, token2 ")
    
    allowlist = Allowlist.from_env()
    
    assert allowlist.is_tool_allowed("tool1")
    assert allowlist.is_tool_allowed("tool2")
    assert allowlist.is_caller_allowed("token1")
    assert allowlist.is_caller_allowed("token2")
