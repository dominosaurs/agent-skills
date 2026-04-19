#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


HOME = Path.home()
DEFAULT_LOCAL_REPO = HOME / "codes" / "mempalace"
CODEX_CONFIG = HOME / ".codex" / "config.toml"
CODEX_HOOKS = HOME / ".codex" / "hooks.json"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.local.json"
GEMINI_SETTINGS = HOME / ".gemini" / "settings.json"
SUPPORTED_PROTOCOL_VERSION = "2025-03-26"
BROKEN_VENV_EXIT = 2


def dedicated_venv_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else HOME / ".local" / "share"
    return base / "mempalace-librarian" / "venv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install and wire MemPalace for Codex/Claude/Gemini.",
    )
    parser.add_argument(
        "--install-source",
        choices=["auto", "local", "pypi"],
        default="pypi",
        help="Install source for dedicated runtime creation.",
    )
    parser.add_argument(
        "--repo",
        default=str(DEFAULT_LOCAL_REPO),
        help="Local MemPalace repo path for editable install.",
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Optional custom palace path passed to MCP server.",
    )
    parser.add_argument(
        "--skip-hooks",
        action="store_true",
        help="Do not configure hooks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without mutating files.",
    )
    return parser.parse_args()


def log(msg: str) -> None:
    print(msg)


def run(cmd: Sequence[str], dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess | None:
    log("$ " + " ".join(shlex.quote(part) for part in cmd))
    if dry_run:
        return None
    return subprocess.run(cmd, check=check, text=True)


def capture(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def require_python() -> str:
    for name in ("python3", "python"):
        path = shutil.which(name)
        if not path:
            continue
        out = capture([path, "--version"])
        version_text = (out.stdout or out.stderr).strip()
        parts = version_text.split()
        version = parts[-1] if parts else "0"
        major, minor, *_ = [int(x) for x in version.split(".")]
        if (major, minor) >= (3, 9):
            return path
    raise SystemExit("Python 3.9+ required")


def select_install_source(mode: str, repo: Path) -> tuple[str, list[str]]:
    if mode == "local":
        if not repo.exists():
            raise SystemExit(f"Local repo not found: {repo}")
        return "local", ["-e", str(repo)]
    if mode == "pypi":
        return "pypi", ["mempalace"]
    if repo.exists():
        return "local", ["-e", str(repo)]
    return "pypi", ["mempalace"]


def mcp_args(palace: str | None) -> list[str]:
    args = ["-m", "mempalace.mcp_server"]
    if palace:
        args.extend(["--palace", palace])
    return args


def verify_cli(venv_python: Path, dry_run: bool) -> bool:
    result = run(
        [str(venv_python), "-m", "mempalace", "status"],
        dry_run=dry_run,
        check=False,
    )
    return True if dry_run else result is not None and result.returncode == 0


def verify_imports(venv_python: Path, dry_run: bool) -> bool:
    result = run(
        [str(venv_python), "-c", "import mempalace, mempalace.mcp_server"],
        dry_run=dry_run,
        check=False,
    )
    return True if dry_run else result is not None and result.returncode == 0


def verify_mcp_server(venv_python: Path, palace: str | None, dry_run: bool) -> bool:
    if dry_run:
        run([str(venv_python), "-c", "import mempalace.mcp_server"], dry_run=True)
        log("$ MCP initialize/tools/list handshake")
        return True

    proc = subprocess.Popen(
        [str(venv_python), *mcp_args(palace)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": SUPPORTED_PROTOCOL_VERSION, "capabilities": {}},
        }
        tools_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()
        init_line = proc.stdout.readline().strip()
        if not init_line:
            return False
        init_resp = json.loads(init_line)
        name = init_resp.get("result", {}).get("serverInfo", {}).get("name")
        if name != "mempalace":
            return False

        proc.stdin.write(json.dumps(tools_req) + "\n")
        proc.stdin.flush()
        tools_line = proc.stdout.readline().strip()
        if not tools_line:
            return False
        tools_resp = json.loads(tools_line)
        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = {tool.get("name") for tool in tools}
        return "mempalace_status" in tool_names
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)


def ensure_venv(venv: Path, python_bin: str, dry_run: bool) -> Path:
    if not (venv / "bin" / "python").exists():
        run([python_bin, "-m", "venv", str(venv)], dry_run=dry_run)
    return venv / "bin" / "python"


def install_mempalace(venv_python: Path, install_args: list[str], dry_run: bool) -> None:
    run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run)
    run([str(venv_python), "-m", "pip", "install", *install_args], dry_run=dry_run)


def fail_broken_dedicated_venv(venv_python: Path, failures: list[str]) -> None:
    log(f"Dedicated MemPalace runtime is broken: {venv_python}")
    log("Checks failed: " + ", ".join(failures))
    log("No config changes were applied.")
    raise SystemExit(BROKEN_VENV_EXIT)


def ensure_dedicated_runtime(
    venv: Path,
    python_bin: str,
    install_args: list[str],
    dry_run: bool,
) -> Path:
    venv_python = venv / "bin" / "python"
    if not venv.exists():
        log(f"Creating dedicated runtime: {venv}")
        created_python = ensure_venv(venv, python_bin, dry_run)
        install_mempalace(created_python, install_args, dry_run)
        return created_python

    if not venv_python.exists():
        fail_broken_dedicated_venv(venv_python, ["missing python executable"])

    failures: list[str] = []
    if not verify_cli(venv_python, dry_run):
        failures.append("mempalace status")
    if not verify_imports(venv_python, dry_run):
        failures.append("mempalace imports")
    if failures:
        fail_broken_dedicated_venv(venv_python, failures)

    return venv_python


def render_codex_mcp_config(existing: str, venv_python: Path, palace: str | None) -> str:
    lines = existing.splitlines()
    start = None
    end = None
    for idx, line in enumerate(lines):
        if line.strip() == "[mcp_servers.mempalace]":
            start = idx
            end = len(lines)
            for j in range(idx + 1, len(lines)):
                if lines[j].startswith("[") and lines[j].endswith("]"):
                    end = j
                    break
            break
    block = [
        "[mcp_servers.mempalace]",
        f'command = "{str(venv_python)}"',
        "args = [" + ", ".join(f'"{arg}"' for arg in mcp_args(palace)) + "]",
    ]
    if start is None:
        return existing.rstrip() + ("\n\n" if existing.strip() else "") + "\n".join(block) + "\n"
    new_lines = lines[:start] + block + lines[end:]
    return "\n".join(new_lines).rstrip() + "\n"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def hook_command(venv_python: Path, hook_name: str, harness: str) -> str:
    return " ".join(
        [
            shlex.quote(str(venv_python)),
            "-m",
            "mempalace",
            "hook",
            "run",
            "--hook",
            hook_name,
            "--harness",
            harness,
        ]
    )


def is_mempalace_hook_command(command: str, hook_name: str, harness: str) -> bool:
    return (
        " -m mempalace hook run " in command
        and f"--hook {hook_name}" in command
        and f"--harness {harness}" in command
    )


def codex_hooks_payload(data: dict, venv_python: Path) -> dict:
    stop_entry = {
        "type": "command",
        "command": hook_command(venv_python, "stop", "codex"),
        "timeout": 30,
    }
    pre_entry = {
        "type": "command",
        "command": hook_command(venv_python, "precompact", "codex"),
        "timeout": 30,
    }
    stop_hooks = [
        entry
        for entry in list(data.get("Stop", []))
        if not is_mempalace_hook_command(entry.get("command", ""), "stop", "codex")
    ]
    pre_hooks = [
        entry
        for entry in list(data.get("PreCompact", []))
        if not is_mempalace_hook_command(entry.get("command", ""), "precompact", "codex")
    ]
    stop_hooks.append(stop_entry)
    pre_hooks.append(pre_entry)
    data["Stop"] = stop_hooks
    data["PreCompact"] = pre_hooks
    return data


def _claude_has_mempalace_hook(entry: dict, hook_name: str, harness: str) -> bool:
    for hook in entry.get("hooks", []):
        if is_mempalace_hook_command(hook.get("command", ""), hook_name, harness):
            return True
    return False


def claude_settings_payload(data: dict, venv_python: Path, palace: str | None, include_hooks: bool) -> dict:
    mcp_servers = data.setdefault("mcpServers", {})
    mcp_servers["mempalace"] = {
        "command": str(venv_python),
        "args": mcp_args(palace),
    }
    if not include_hooks:
        return data

    hooks = data.setdefault("hooks", {})
    stop_list = [
        entry
        for entry in list(hooks.get("Stop", []))
        if not _claude_has_mempalace_hook(entry, "stop", "claude-code")
    ]
    pre_list = [
        entry
        for entry in list(hooks.get("PreCompact", []))
        if not _claude_has_mempalace_hook(entry, "precompact", "claude-code")
    ]
    stop_list.append(
        {
            "matcher": "*",
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command(venv_python, "stop", "claude-code"),
                    "timeout": 30,
                }
            ],
        }
    )
    pre_list.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": hook_command(venv_python, "precompact", "claude-code"),
                    "timeout": 30,
                }
            ],
        }
    )
    hooks["Stop"] = stop_list
    hooks["PreCompact"] = pre_list
    return data


def resolve_gemini_precompress_command(venv_python: Path, repo: Path, dry_run: bool = False) -> str:
    packaged = venv_python.parent.parent / "mempalace" / "hooks" / "mempal_precompact_hook.sh"
    if packaged.exists():
        return str(packaged)
    repo_hook = repo / "hooks" / "mempal_precompact_hook.sh"
    if repo_hook.exists():
        return str(repo_hook)
    if dry_run:
        return str(packaged)
    raise SystemExit("Gemini hook script not found for MemPalace")


def _gemini_has_mempalace_precompress(entry: dict) -> bool:
    for hook in entry.get("hooks", []):
        command = hook.get("command", "")
        if command.endswith("/mempal_precompact_hook.sh"):
            return True
    return False


def gemini_settings_payload(
    data: dict,
    venv_python: Path,
    palace: str | None,
    repo: Path,
    include_hooks: bool,
    dry_run: bool,
) -> dict:
    mcp_servers = data.setdefault("mcpServers", {})
    mcp_servers["mempalace"] = {
        "command": str(venv_python),
        "args": mcp_args(palace),
    }
    if not include_hooks:
        return data

    hooks = data.setdefault("hooks", {})
    precompress_cmd = resolve_gemini_precompress_command(venv_python, repo, dry_run=dry_run)
    existing = [
        entry for entry in list(hooks.get("PreCompress", [])) if not _gemini_has_mempalace_precompress(entry)
    ]
    existing.append(
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": precompress_cmd}],
        }
    )
    hooks["PreCompress"] = existing
    return data


def verify_codex_mcp(config_path: Path, venv_python: Path, palace: str | None) -> None:
    if tomllib is None or not config_path.exists():
        return
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    server = data.get("mcp_servers", {}).get("mempalace", {})
    if server.get("command") != str(venv_python):
        raise SystemExit("Codex MCP command mismatch after config write")
    if server.get("args") != mcp_args(palace):
        raise SystemExit("Codex MCP args mismatch after config write")


def verify_claude_settings(path: Path, venv_python: Path, palace: str | None, include_hooks: bool) -> None:
    data = load_json(path)
    server = data.get("mcpServers", {}).get("mempalace", {})
    if server.get("command") != str(venv_python):
        raise SystemExit("Claude MCP command mismatch after config write")
    if server.get("args") != mcp_args(palace):
        raise SystemExit("Claude MCP args mismatch after config write")
    if include_hooks:
        hooks = data.get("hooks", {})
        if "Stop" not in hooks or "PreCompact" not in hooks:
            raise SystemExit("Claude hook entries missing after config write")


def verify_gemini_settings(path: Path, venv_python: Path, palace: str | None, include_hooks: bool) -> None:
    data = load_json(path)
    server = data.get("mcpServers", {}).get("mempalace", {})
    if server.get("command") != str(venv_python):
        raise SystemExit("Gemini MCP command mismatch after config write")
    if server.get("args") != mcp_args(palace):
        raise SystemExit("Gemini MCP args mismatch after config write")
    if include_hooks:
        hooks = data.get("hooks", {}).get("PreCompress", [])
        if not any(_gemini_has_mempalace_precompress(entry) for entry in hooks):
            raise SystemExit("Gemini PreCompress hook missing MemPalace entry")


def atomic_write_text(path: Path, text: str, dry_run: bool) -> None:
    log(f"Update {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp_file:
        tmp_file.write(text)
        tmp_name = tmp_file.name
    Path(tmp_name).replace(path)


def apply_updates(updates: list[tuple[Path, str]], dry_run: bool) -> None:
    for path, text in updates:
        atomic_write_text(path, text, dry_run=dry_run)


def main() -> None:
    args = parse_args()
    python_bin = require_python()
    repo = Path(args.repo).expanduser()
    source_label, install_args = select_install_source(args.install_source, repo)
    venv = dedicated_venv_path()
    venv_python = ensure_dedicated_runtime(
        venv=venv,
        python_bin=python_bin,
        install_args=install_args,
        dry_run=args.dry_run,
    )
    log(f"Dedicated runtime: {venv_python}")
    if source_label == "pypi":
        log("Install source: pypi")
    elif source_label == "local":
        log(f"Install source: local ({repo})")

    if not verify_cli(venv_python, args.dry_run):
        fail_broken_dedicated_venv(venv_python, ["mempalace status"])
    if not verify_imports(venv_python, args.dry_run):
        fail_broken_dedicated_venv(venv_python, ["mempalace imports"])
    if not verify_mcp_server(venv_python, args.palace, args.dry_run):
        fail_broken_dedicated_venv(venv_python, ["mcp handshake"])

    codex_existing = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""
    codex_next = render_codex_mcp_config(codex_existing, venv_python, args.palace)
    codex_hooks_data = codex_hooks_payload(load_json(CODEX_HOOKS), venv_python) if not args.skip_hooks else None
    claude_data = claude_settings_payload(
        load_json(CLAUDE_SETTINGS),
        venv_python,
        args.palace,
        include_hooks=not args.skip_hooks,
    )
    gemini_data = gemini_settings_payload(
        load_json(GEMINI_SETTINGS),
        venv_python,
        args.palace,
        repo,
        include_hooks=not args.skip_hooks,
        dry_run=args.dry_run,
    )

    updates: list[tuple[Path, str]] = [(CODEX_CONFIG, codex_next)]
    if codex_hooks_data is not None:
        updates.append((CODEX_HOOKS, json.dumps(codex_hooks_data, indent=2) + "\n"))
    updates.append((CLAUDE_SETTINGS, json.dumps(claude_data, indent=2) + "\n"))
    updates.append((GEMINI_SETTINGS, json.dumps(gemini_data, indent=2) + "\n"))
    apply_updates(updates, dry_run=args.dry_run)

    if not args.dry_run:
        verify_codex_mcp(CODEX_CONFIG, venv_python, args.palace)
        verify_claude_settings(CLAUDE_SETTINGS, venv_python, args.palace, include_hooks=not args.skip_hooks)
        verify_gemini_settings(GEMINI_SETTINGS, venv_python, args.palace, include_hooks=not args.skip_hooks)

    log("MemPalace setup flow complete.")


if __name__ == "__main__":
    main()
