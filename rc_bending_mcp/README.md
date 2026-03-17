# `rc_bending_mcp` Folder

This folder stores the local stdio MCP server and its automation helpers for the Streamlit reinforced-concrete calculator.

## Contents
- `__init__.py` - package marker that exposes the MCP server builder.
- `__main__.py` - module entrypoint so the server can be launched with `python -m rc_bending_mcp`.
- `adapters.py` - converts machine-facing MCP payloads into the existing Streamlit/domain draft formats.
- `artifacts.py` - output-directory resolution and artifact-writing helpers for MCP tool runs.
- `domain.py` - direct Python execution layer for section, serviceability, and experimental workflows.
- `handlers.py` - high-level tool handlers that build response envelopes, compare Python/UI outputs, and manage artifacts.
- `server.py` - MCP tool registration for the public stdio server.
- `ui_runner.py` - Playwright-backed Streamlit automation runner that starts the local app and reads hidden automation payloads.
