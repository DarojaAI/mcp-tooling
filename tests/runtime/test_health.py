"""Tests for runtime.health"""

import time
from runtime.health import health_report
from runtime.registry import ToolRegistry
from runtime.base import BaseTool


class DummyTool(BaseTool):
    """Dummy tool for testing."""
    
    @property
    def tool_name(self) -> str:
        return "dummy"
    
    @property
    def description(self) -> str:
        return "A dummy tool"
    
    @property
    def input_schema(self) -> dict:
        return {"type": "object"}
    
    async def call(self, args: dict) -> dict:
        return {}


def test_health_report_basic():
    """Test basic health report."""
    registry = ToolRegistry()
    start_time = time.time()
    
    report = health_report(start_time, registry)
    
    assert report["status"] == "healthy"
    assert "version" in report
    assert "uptime_seconds" in report
    assert report["tools_registered"] == 0
    assert report["tools"] == []


def test_health_report_with_tools():
    """Test health report with registered tools."""
    registry = ToolRegistry()
    registry.register(DummyTool())
    
    start_time = time.time()
    report = health_report(start_time, registry)
    
    assert report["tools_registered"] == 1
    assert "dummy" in report["tools"]


def test_health_report_uptime():
    """Test that uptime increases."""
    registry = ToolRegistry()
    start_time = time.time()
    
    time.sleep(0.1)  # Wait a bit
    
    report = health_report(start_time, registry)
    assert report["uptime_seconds"] >= 0.1
