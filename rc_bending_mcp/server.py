from __future__ import annotations

from pathlib import Path

from rc_bending_mcp.handlers import (
    execute_analyze_experimental_workbook,
    execute_build_experimental_template,
    execute_calculate_section,
    execute_calculate_serviceability,
    execute_get_catalogs,
)


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("The Python MCP SDK is not installed. Install the project requirements first.") from error

    server = FastMCP("rc-bending-calculator")

    @server.tool()
    def get_catalogs() -> dict[str, object]:
        return execute_get_catalogs()

    @server.tool()
    def calculate_section(
        section_input: dict[str, object],
        selected_step: int | None = None,
        output_dir: str | None = None,
    ) -> dict[str, object]:
        return execute_calculate_section(section_input, selected_step=selected_step, output_dir=_normalize_output_dir(output_dir))

    @server.tool()
    def calculate_serviceability(
        section_input: dict[str, object],
        serviceability_input: dict[str, object],
        selected_step: int | None = None,
        output_dir: str | None = None,
    ) -> dict[str, object]:
        return execute_calculate_serviceability(
            section_input,
            serviceability_input,
            selected_step=selected_step,
            output_dir=_normalize_output_dir(output_dir),
        )

    @server.tool()
    def analyze_experimental_workbook(
        workbook_path: str,
        section_input: dict[str, object],
        serviceability_input: dict[str, object] | None = None,
        selected_step: int | None = None,
        output_dir: str | None = None,
    ) -> dict[str, object]:
        return execute_analyze_experimental_workbook(
            workbook_path,
            section_input,
            serviceability_input=serviceability_input,
            selected_step=selected_step,
            output_dir=_normalize_output_dir(output_dir),
        )

    @server.tool()
    def build_experimental_template(output_dir: str | None = None) -> dict[str, object]:
        return execute_build_experimental_template(output_dir=_normalize_output_dir(output_dir))

    return server


def main() -> None:
    build_server().run()


def _normalize_output_dir(output_dir: str | None) -> str | Path | None:
    if output_dir in {None, ""}:
        return None
    return Path(output_dir)
