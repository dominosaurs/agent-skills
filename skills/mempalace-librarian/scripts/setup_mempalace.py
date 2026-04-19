#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


HOME = Path.home()
DEFAULT_VENV = HOME / ".mempalace" / "venv"
DEFAULT_LOCAL_REPO = HOME / "codes" / "mempalace"
FALLBACK_EXISTING_VENV = HOME / ".venv" / "bin" / "python"
CODEX_CONFIG = HOME / ".codex" / "config.toml"
CODEX_HOOKS = HOME / ".codex" / "hooks.json"
CLAUDE_SETTINGS = HOME / ".claude" / "settings.local.json"
GEMINI_SETTINGS = HOME / ".gemini" / "settings.json"
SUPPORTED_PROTOCOL_VERSION = "2025-03-26"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install and wire MemPalace for Codex/Claude."
    )
    parser.add_argument(
        "--harness",
        choices=["auto", "codex", "claude", "gemini", "both", "all"],
        default="auto",
        help="Which harnesses to configure.",
    )
    parser.add_argument(
        "--venv",
        default=str(DEFAULT_VENV),
        help="Dedicated MemPalace virtualenv path.",
    )
    parser.add_argument(
        "--install-source",
        choices=["auto", "local", "pypi"],
        default="auto",
        help="Install from local repo if present, else PyPI.",
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
        if path:
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


def has_mempalace(python_bin: Path) -> bool:
    if not python_bin.exists():
        return False
    result = subprocess.run(
        [str(python_bin), "-m", "mempalace", "status"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def configured_mcp_python_candidates(harnesses: Sequence[str]) -> list[Path]:
    candidates: list[Path] = []
    if "codex" in harnesses and tomllib is not None and CODEX_CONFIG.exists():
        data = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
        path = mcp_python_from_server(data.get("mcp_servers", {}).get("mempalace", {}))
        if path is not None:
            candidates.append(path)
    if "gemini" in harnesses and GEMINI_SETTINGS.exists():
        data = json.loads(GEMINI_SETTINGS.read_text(encoding="utf-8"))
        path = mcp_python_from_server(data.get("mcpServers", {}).get("mempalace", {}))
        if path is not None:
            candidates.append(path)
    return candidates


def mcp_python_from_server(server: dict) -> Path | None:
    command = server.get("command")
    args = server.get("args", [])
    if not command or not isinstance(args, list):
        return None
    if args[:2] != ["-m", "mempalace.mcp_server"]:
        return None
    resolved = shutil.which(command) if "/" not in command else command
    if not resolved:
        return None
    return Path(resolved).expanduser()


def find_existing_mempalace_python(
    preferred_venv: Path,
    configured_candidates: Sequence[Path] = (),
) -> Path | None:
    preferred_python = preferred_venv / "bin" / "python"
    if preferred_venv == DEFAULT_VENV:
        candidates = [*configured_candidates, preferred_python, FALLBACK_EXISTING_VENV]
    else:
        candidates = [preferred_python, *configured_candidates, FALLBACK_EXISTING_VENV]
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if has_mempalace(candidate):
            return candidate
    return None


def ensure_venv(venv: Path, python_bin: str, dry_run: bool) -> Path:
    if not (venv / "bin" / "python").exists():
        run([python_bin, "-m", "venv", str(venv)], dry_run=dry_run)
    return venv / "bin" / "python"


def install_mempalace(venv_python: Path, install_args: list[str], dry_run: bool) -> None:
    run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run)
    run([str(venv_python), "-m", "pip", "install", *install_args], dry_run=dry_run)


def verify_cli(venv_python: Path, dry_run: bool) -> None:
    run([str(venv_python), "-m", "mempalace", "status"], dry_run=dry_run)


def verify_mcp_server(venv_python: Path, palace: str | None, dry_run: bool) -> None:
    if dry_run:
        run([str(venv_python), "-c", "import mempalace.mcp_server"], dry_run=True)
        log("$ " + "MCP initialize/tools/list handshake")
        return

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
            raise SystemExit("MCP server gave no initialize response")
        init_resp = json.loads(init_line)
        name = init_resp.get("result", {}).get("serverInfo", {}).get("name")
        if name != "mempalace":
            raise SystemExit("MCP initialize response invalid")

        proc.stdin.write(json.dumps(tools_req) + "\n")
        proc.stdin.flush()
        tools_line = proc.stdout.readline().strip()
        if not tools_line:
            raise SystemExit("MCP server gave no tools/list response")
        tools_resp = json.loads(tools_line)
        tools = tools_resp.get("result", {}).get("tools", [])
        tool_names = {tool.get("name") for tool in tools}
        if "mempalace_status" not in tool_names:
            raise SystemExit("MCP tools/list missing mempalace_status")
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=5)


def mcp_args(palace: str | None) -> list[str]:
    args = ["-m", "mempalace.mcp_server"]
    if palace:
        args.extend(["--palace", palace])
    return args


def manual_claude_mcp_command(venv_python: Path, palace: str | None) -> str:
    return " ".join(
        ["claude", "mcp", "add", "mempalace", "--", shlex.quote(str(venv_python)), *mcp_args(palace)]
    )


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


def detect_harnesses(mode: str) -> list[str]:
    if mode == "all":
        return ["codex", "claude", "gemini"]
    if mode == "both":
        return ["codex", "claude"]
    if mode in {"codex", "claude", "gemini"}:
        return [mode]
    found = []
    if CODEX_CONFIG.exists() or (HOME / ".codex").exists():
        found.append("codex")
    if (HOME / ".claude").exists() or shutil.which("claude"):
        found.append("claude")
    if GEMINI_SETTINGS.exists() or (HOME / ".gemini").exists() or shutil.which("gemini"):
        found.append("gemini")
    return found or ["codex"]


def upsert_codex_mcp(config_path: Path, venv_python: Path, palace: str | None, dry_run: bool) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
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
        new_text = existing.rstrip() + ("\n\n" if existing.strip() else "") + "\n".join(block) + "\n"
    else:
        new_lines = lines[:start] + block + lines[end:]
        new_text = "\n".join(new_lines).rstrip() + "\n"
    log(f"Update {config_path}")
    if not dry_run:
        config_path.write_text(new_text, encoding="utf-8")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict, dry_run: bool) -> None:
    log(f"Update {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_codex_hooks(path: Path, venv_python: Path, dry_run: bool) -> None:
    data = load_json(path)
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
    stop_hooks = list(data.get("Stop", []))
    pre_hooks = list(data.get("PreCompact", []))
    stop_hooks = [
        entry
        for entry in stop_hooks
        if not is_mempalace_hook_command(entry.get("command", ""), "stop", "codex")
    ]
    pre_hooks = [
        entry
        for entry in pre_hooks
        if not is_mempalace_hook_command(entry.get("command", ""), "precompact", "codex")
    ]
    stop_hooks.append(stop_entry)
    pre_hooks.append(pre_entry)
    data["Stop"] = stop_hooks
    data["PreCompact"] = pre_hooks
    write_json(path, data, dry_run)


def ensure_claude_hooks(path: Path, venv_python: Path, dry_run: bool) -> None:
    data = load_json(path)
    hooks = data.setdefault("hooks", {})
    stop_list = hooks.setdefault("Stop", [])
    pre_list = hooks.setdefault("PreCompact", [])
    stop_cmd = hook_command(venv_python, "stop", "claude-code")
    pre_cmd = hook_command(venv_python, "precompact", "claude-code")

    stop_wrapper = {
        "matcher": "*",
        "hooks": [{"type": "command", "command": stop_cmd, "timeout": 30}],
    }
    pre_wrapper = {
        "hooks": [{"type": "command", "command": pre_cmd, "timeout": 30}],
    }

    stop_list = [
        entry for entry in stop_list if not _claude_has_mempalace_hook(entry, "stop", "claude-code")
    ]
    pre_list = [
        entry
        for entry in pre_list
        if not _claude_has_mempalace_hook(entry, "precompact", "claude-code")
    ]
    stop_list.append(stop_wrapper)
    pre_list.append(pre_wrapper)
    hooks["Stop"] = stop_list
    hooks["PreCompact"] = pre_list
    write_json(path, data, dry_run)


def _claude_has_command(entry: dict, command: str) -> bool:
    for hook in entry.get("hooks", []):
        if hook.get("command") == command:
            return True
    return False


def _claude_has_mempalace_hook(entry: dict, hook_name: str, harness: str) -> bool:
    for hook in entry.get("hooks", []):
        if is_mempalace_hook_command(hook.get("command", ""), hook_name, harness):
            return True
    return False


def configure_claude_mcp(venv_python: Path, palace: str | None, dry_run: bool) -> None:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit(
            "Claude CLI not found. Cannot auto-configure Claude MCP. "
            f"Manual command: {manual_claude_mcp_command(venv_python, palace)}"
        )
    run([claude, "mcp", "add", "mempalace", "--", str(venv_python), *mcp_args(palace)], dry_run=dry_run)


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


def ensure_gemini_settings(
    path: Path,
    venv_python: Path,
    palace: str | None,
    repo: Path,
    dry_run: bool,
) -> None:
    data = load_json(path)
    mcp_servers = data.setdefault("mcpServers", {})
    mcp_servers["mempalace"] = {
        "command": str(venv_python),
        "args": mcp_args(palace),
    }

    hooks = data.setdefault("hooks", {})
    precompress_cmd = resolve_gemini_precompress_command(venv_python, repo, dry_run=dry_run)
    precompress_wrapper = {
        "matcher": "*",
        "hooks": [{"type": "command", "command": precompress_cmd}],
    }
    existing = list(hooks.get("PreCompress", []))
    existing = [
        entry for entry in existing if not _gemini_has_mempalace_precompress(entry)
    ]
    existing.append(precompress_wrapper)
    hooks["PreCompress"] = existing
    write_json(path, data, dry_run)


def _gemini_has_mempalace_precompress(entry: dict) -> bool:
    for hook in entry.get("hooks", []):
        command = hook.get("command", "")
        if command.endswith("/mempal_precompact_hook.sh"):
            return True
    return False


def verify_gemini_settings(path: Path, venv_python: Path, palace: str | None) -> None:
    if not path.exists():
        raise SystemExit(f"Missing Gemini settings: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    server = data.get("mcpServers", {}).get("mempalace", {})
    if server.get("command") != str(venv_python):
        raise SystemExit("Gemini MCP command mismatch after config write")
    if server.get("args") != mcp_args(palace):
        raise SystemExit("Gemini MCP args mismatch after config write")
    hooks = data.get("hooks", {}).get("PreCompress", [])
    if not any(_gemini_has_mempalace_precompress(entry) for entry in hooks):
        raise SystemExit("Gemini PreCompress hook missing MemPalace entry")


def verify_codex_mcp(config_path: Path, venv_python: Path, palace: str | None) -> None:
    if tomllib is None or not config_path.exists():
        return
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    server = data.get("mcp_servers", {}).get("mempalace", {})
    if server.get("command") != str(venv_python):
        raise SystemExit("Codex MCP command mismatch after config write")
    if server.get("args") != mcp_args(palace):
        raise SystemExit("Codex MCP args mismatch after config write")


def verify_hooks_json(path: Path, key: str) -> None:
    if not path.exists():
        raise SystemExit(f"Missing hook config: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if key not in data:
        raise SystemExit(f"Missing hook key {key} in {path}")


def main() -> None:
    args = parse_args()
    python_bin = require_python()
    venv = Path(args.venv).expanduser()
    repo = Path(args.repo).expanduser()
    harnesses = detect_harnesses(args.harness)
    source_label, install_args = select_install_source(args.install_source, repo)
    configured_candidates = configured_mcp_python_candidates(harnesses)
    existing_python = find_existing_mempalace_python(venv, configured_candidates)
    if existing_python is not None:
        venv_python = existing_python
        log(f"Reusing existing MemPalace install: {venv_python}")
    else:
        log(f"Install source: {source_label}")
        venv_python = ensure_venv(venv, python_bin, args.dry_run)
        install_mempalace(venv_python, install_args, args.dry_run)

    verify_cli(venv_python, args.dry_run)
    verify_mcp_server(venv_python, args.palace, args.dry_run)

    if "codex" in harnesses:
        upsert_codex_mcp(CODEX_CONFIG, venv_python, args.palace, args.dry_run)
        if not args.dry_run:
            verify_codex_mcp(CODEX_CONFIG, venv_python, args.palace)
        if not args.skip_hooks:
            ensure_codex_hooks(CODEX_HOOKS, venv_python, args.dry_run)
            if not args.dry_run:
                verify_hooks_json(CODEX_HOOKS, "Stop")
                verify_hooks_json(CODEX_HOOKS, "PreCompact")

    if "claude" in harnesses:
        configure_claude_mcp(venv_python, args.palace, args.dry_run)
        if not args.skip_hooks:
            ensure_claude_hooks(CLAUDE_SETTINGS, venv_python, args.dry_run)
            if not args.dry_run:
                verify_hooks_json(CLAUDE_SETTINGS, "hooks")

    if "gemini" in harnesses:
        ensure_gemini_settings(GEMINI_SETTINGS, venv_python, args.palace, repo, args.dry_run)
        if not args.dry_run:
            verify_gemini_settings(GEMINI_SETTINGS, venv_python, args.palace)

    log("MemPalace setup flow complete.")


if __name__ == "__main__":
    main()
