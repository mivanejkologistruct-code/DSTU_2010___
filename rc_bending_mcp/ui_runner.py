from __future__ import annotations

from collections.abc import Mapping
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from rc_bending_mcp.artifacts import BASE_DIR, build_artifact, write_json_artifact, write_text_artifact


class UIUnavailableError(RuntimeError):
    """Raised when the local Streamlit UI automation cannot be executed."""


class StreamlitUIRunner:
    def __init__(self, *, app_path: Path | None = None) -> None:
        self._app_path = app_path or (BASE_DIR / "streamlit_app.py")

    def run_section(
        self,
        *,
        draft_inputs: Mapping[str, object],
        selected_step: int,
        expected_python_result: Mapping[str, object],
        output_dir: Path,
    ) -> dict[str, object]:
        request = {
            "workflow": "section",
            "section_input": _extract_section_machine_input(draft_inputs),
            "selected_step": selected_step,
            "expected_python_result": dict(expected_python_result),
        }
        return self._run_workflow("section", request, output_dir, marker="automation-section-payload")

    def run_serviceability(
        self,
        *,
        draft_inputs: Mapping[str, object],
        serviceability_draft_inputs: Mapping[str, object],
        selected_step: int,
        expected_python_result: Mapping[str, object],
        output_dir: Path,
    ) -> dict[str, object]:
        request = {
            "workflow": "serviceability",
            "section_input": _extract_section_machine_input(draft_inputs),
            "serviceability_input": dict(serviceability_draft_inputs),
            "selected_step": selected_step,
            "expected_python_result": dict(expected_python_result),
        }
        return self._run_workflow("serviceability", request, output_dir, marker="automation-serviceability-payload")

    def run_experimental(
        self,
        *,
        draft_inputs: Mapping[str, object],
        serviceability_draft_inputs: Mapping[str, object],
        workbook_path: str,
        expected_python_result: Mapping[str, object],
        output_dir: Path,
    ) -> dict[str, object]:
        request = {
            "workflow": "experimental",
            "section_input": _extract_section_machine_input(draft_inputs),
            "serviceability_input": dict(serviceability_draft_inputs),
            "workbook_path": workbook_path,
            "expected_python_result": dict(expected_python_result),
        }
        return self._run_workflow("experimental", request, output_dir, marker="automation-experimental-payload")

    def _run_workflow(self, workflow: str, request: dict[str, object], output_dir: Path, *, marker: str) -> dict[str, object]:
        sync_playwright = _load_sync_playwright()
        request_path = output_dir / f"{workflow}-request.json"
        write_json_artifact(request_path, request, label="Automation request")
        stdout_path = output_dir / "streamlit_stdout.log"
        stderr_path = output_dir / "streamlit_stderr.log"
        console_path = output_dir / "browser_console.log"
        screenshot_path = output_dir / f"{workflow}.png"

        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
            port = _pick_free_port()
            process_env = dict(os.environ)
            process_env["RC_BENDING_AUTOMATION"] = "1"
            process_env["RC_BENDING_AUTOMATION_INPUT"] = str(request_path)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(self._app_path),
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                    "--server.port",
                    str(port),
                ],
                cwd=str(BASE_DIR),
                env=process_env,
                stdout=stdout_handle,
                stderr=stderr_handle,
            )
            try:
                _wait_for_streamlit(f"http://127.0.0.1:{port}", process, stderr_path)
                url = f"http://127.0.0.1:{port}/?{urlencode({'automation': '1', 'automation_workflow': workflow, 'automation_input': str(request_path)})}"
                console_messages: list[str] = []
                with sync_playwright() as playwright:
                    try:
                        browser = playwright.chromium.launch()
                    except Exception as error:
                        raise UIUnavailableError(
                            "Playwright Chromium is unavailable. Run `python -m playwright install chromium`."
                        ) from error
                    page = browser.new_page(viewport={"width": 1440, "height": 1280})
                    page.on("console", lambda message: console_messages.append(f"{message.type}: {message.text}"))
                    page.goto(url, wait_until="networkidle")
                    locator = page.locator(f'[data-role="{marker}"]')
                    locator.wait_for(state="attached", timeout=30000)
                    payload = json.loads(locator.text_content() or "{}")
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    browser.close()
                return {
                    "payload": payload,
                    "artifacts": [
                        build_artifact(label="UI screenshot", path=screenshot_path, kind="image"),
                        write_text_artifact(console_path, "\n".join(console_messages), label="Browser console log"),
                        build_artifact(label="Streamlit stdout", path=stdout_path, kind="log"),
                        build_artifact(label="Streamlit stderr", path=stderr_path, kind="log"),
                    ],
                    "messages": [f"Executed {workflow} through the local Streamlit UI."],
                }
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()


def _load_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise UIUnavailableError(
            "Python Playwright is not installed. Install dependencies and run `python -m playwright install chromium`."
        ) from error
    return sync_playwright


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_streamlit(base_url: str, process: subprocess.Popen[str], stderr_path: Path) -> None:
    deadline = time.monotonic() + 45.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr_text = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
            raise UIUnavailableError(f"Streamlit failed to start. {stderr_text.strip()}".strip())
        try:
            with urlopen(base_url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise UIUnavailableError("Timed out waiting for the local Streamlit application to become ready.")


def _extract_section_machine_input(draft_inputs: Mapping[str, object]) -> dict[str, object]:
    concrete_layers = list(draft_inputs["concrete_layers"])
    rebar_layers = list(draft_inputs["rebar_layers"])
    return {
        "section_height_mm": float(draft_inputs["section_height_mm"]),
        "section_width_mm": float(draft_inputs["section_width_mm"]),
        "outer_steps": int(draft_inputs["outer_steps"]),
        "concrete_layers": [
            {
                "height_mm": float(concrete_layers[0]["height_mm"]),
                "concrete_class": str(concrete_layers[0]["concrete_class"]),
            },
            {
                "height_mm": float(concrete_layers[1]["height_mm"]),
                "concrete_class": str(concrete_layers[1]["concrete_class"]),
            },
        ],
        "rebar_layers": [_extract_rebar_machine_row(rebar_layer) for rebar_layer in rebar_layers],
    }


def _extract_rebar_machine_row(rebar_layer: Mapping[str, object]) -> dict[str, object]:
    face = "top" if str(rebar_layer["face"]) == "Верхня" else "bottom"
    return {
        "face": face,
        "distance_mm": float(rebar_layer["distance_mm"]),
        "bar_count": int(rebar_layer["bar_count"]),
        "diameter_mm": int(rebar_layer["diameter_mm"]),
        "steel_class": str(rebar_layer["steel_class"]),
    }
