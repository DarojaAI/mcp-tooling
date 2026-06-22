"""Google Workspace MCP tools.

Narrow tool surface: only operations permitted by the drive.file +
documents scope allowlist. Adding a tool that needs a broader scope
(e.g., gmail.read) requires adding that scope to ALLOWED_SCOPES in
servers/google_workspace/scope_guard.py — the server will refuse to
start otherwise.
"""

from servers.google_workspace.tools.create_document import CreateDocumentTool
from servers.google_workspace.tools.drive_create_file import DriveCreateFileTool
from servers.google_workspace.tools.drive_list_files import DriveListFilesTool
from servers.google_workspace.tools.drive_update_file import DriveUpdateFileTool
from servers.google_workspace.tools.get_document import GetDocumentTool

__all__ = [
    "CreateDocumentTool",
    "DriveCreateFileTool",
    "DriveListFilesTool",
    "DriveUpdateFileTool",
    "GetDocumentTool",
]
