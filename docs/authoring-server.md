# Authoring a New MCP Server

This guide walks you through adding a new capability server to mcp-tooling.

## Overview

Each server in `servers/<name>/` is a **capability adapter** that wraps an external API with MCP tool interfaces.

The `runtime/` framework handles:
- Tool registration and dispatch
- Stdio/HTTP serving
- Health checks
- Allowlists (tool names + caller tokens)
- Secrets loading

You just write the tool logic.

## Step-by-step

### 1. Create the server directory

```bash
mkdir -p servers/<name>/{tools,tests}
touch servers/<name>/__init__.py
touch servers/<name>/tools/__init__.py
```

### 2. Write your tools

Each tool is a subclass of `runtime.base.BaseTool`:

```python
# servers/<name>/tools/my_tool.py

from runtime.base import BaseTool

class MyTool(BaseTool):
    @property
    def tool_name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "Does something useful"
    
    @property
    def input_schema(self) -> dict:
        """JSON Schema for the tool's input arguments."""
        return {
            "type": "object",
            "properties": {
                "arg1": {"type": "string", "description": "First argument"},
                "arg2": {"type": "integer", "description": "Second argument"},
            },
            "required": ["arg1"],
        }
    
    async def call(self, args: dict) -> dict:
        """Execute the tool with the given arguments."""
        arg1 = args["arg1"]
        arg2 = args.get("arg2", 42)
        
        # Do your work here (call external API, etc.)
        result = f"Processed {arg1} with {arg2}"
        
        return {"result": result}
```

### 3. Write the server entrypoint

```python
# servers/<name>/server.py

import asyncio
from runtime.registry import ToolRegistry
from runtime.stdio_server import start_stdio_server
from runtime.http_server import create_app
from servers.<name>.tools.my_tool import MyTool

async def main():
    registry = ToolRegistry()
    
    # Register your tools
    registry.register(MyTool())
    
    # Start stdio server (default)
    # For HTTP: create_app(registry) + uvicorn
    await start_stdio_server(registry)

if __name__ == "__main__":
    asyncio.run(main())
```

### 4. Add tests

```python
# servers/<name>/tests/test_my_tool.py

import pytest
from servers.<name>.tools.my_tool import MyTool

@pytest.mark.asyncio
async def test_my_tool():
    tool = MyTool()
    result = await tool.call({"arg1": "hello"})
    assert result["result"] == "Processed hello with 42"
```

### 5. Add config example

```bash
# servers/<name>/config.example.env

MY_API_KEY=***
MY_API_URL=https://api.example.com
MCPTOOLING_ALLOWED_TOKENS=token1,token2
```

### 6. Update the contract (if deploying)

If your server needs new secrets/vars, add them to `config/dat-contract.yaml`:

```yaml
secrets:
  my_api_key:
    description: "API key for My Service"
    github_secret: "MY_API_KEY"
    required: true
```

Then regenerate the docs:

```bash
python3 scripts/ci/generate-secrets-doc.py
```

### 7. Test locally

```bash
# Install in dev mode
pip install -e '.[dev]'

# Run tests
pytest servers/<name>/tests/

# Run the server
python -m servers.<name>
```

## Best practices

- **Keep tools small:** One tool = one API operation. Don't bundle multiple operations into a single tool.
- **Validate inputs:** Use JSON Schema in `input_schema` to declare required/optional fields and types.
- **Handle errors gracefully:** Return structured error dicts (`{"error": "...", "details": "..."}`) instead of raising exceptions that leak stack traces.
- **Use secrets properly:** Load from `MCPTOOLING_SECRETS_PATH` env var, never hardcode.
- **Test with mocks:** Use `httpx.MockTransport` or similar to test without hitting real APIs.

## Deployment

See [deploy/hetzner/README.md](../deploy/hetzner/README.md) for deploying to Hetzner VMs.

For other platforms (AWS, GCP), the pattern is similar: cloud-init + systemd + rsync.
