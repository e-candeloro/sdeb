from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from . import __version__
except ImportError:  # pragma: no cover - supports direct script execution.
    __version__ = "0.2.1"


DEFAULT_PROJECT = "default"
DEFAULTS = {
    "account": "",
    "partition": "all_serial",
    "node": "",
    "time": "00:20:00",
    "mem": "8G",
    "cpus_per_task": 8,
    "gpu": False,
    "gpus": 1,
    "pty_command": "bash",
}


@dataclass(frozen=True)
class ProjectConfig:
    account: str
    partition: str
    node: str
    time: str
    mem: str
    cpus_per_task: int
    gpu: bool
    gpus: int
    pty_command: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ProjectConfig":
        merged: dict[str, Any] = dict(DEFAULTS)
        merged.update({k: v for k, v in data.items() if v is not None})
        return ProjectConfig(
            account=str(merged["account"]),
            partition=str(merged["partition"]),
            node=str(merged["node"]),
            time=str(merged["time"]),
            mem=str(merged["mem"]),
            cpus_per_task=int(merged["cpus_per_task"]),
            gpu=bool(merged["gpu"]),
            gpus=int(merged["gpus"]),
            pty_command=str(merged["pty_command"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account": self.account,
            "partition": self.partition,
            "node": self.node,
            "time": self.time,
            "mem": self.mem,
            "cpus_per_task": self.cpus_per_task,
            "gpu": self.gpu,
            "gpus": self.gpus,
            "pty_command": self.pty_command,
        }


def _ansi_enabled() -> bool:
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR") is not None:
        return True
    term = os.environ.get("TERM", "")
    if not term or term == "dumb":
        return False
    return sys.stdout.isatty()


def _styled(text: str, sgr: str) -> str:
    if not _ansi_enabled():
        return text
    return f"\x1b[{sgr}m{text}\x1b[0m"


def _bold(text: str) -> str:
    return _styled(text, "1")


def _dim(text: str) -> str:
    return _styled(text, "2")


def _cmd_text(text: str) -> str:
    return _styled(text, "1;36")


def _warn_text(text: str) -> str:
    return _styled(text, "1;33")


def _ok_text(text: str) -> str:
    return _styled(text, "1;32")


def _config_path() -> Path:
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_home).expanduser() if xdg_home else (Path.home() / ".config")
    return base / "sdeb" / "config.json"


def _empty_raw_config() -> dict[str, Any]:
    return {"active_project": "", "projects": {}}


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_raw_config()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in config file: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"Invalid config format (expected object): {path}")

    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}

    active_project = data.get("active_project")
    if not isinstance(active_project, str) or not active_project:
        active_project = ""

    return {
        "active_project": active_project,
        "projects": projects,
    }


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _save_raw_config(path: Path, raw: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(raw, indent=2, sort_keys=True) + "\n")


def _get_project_config(raw: dict[str, Any], project: str) -> ProjectConfig:
    projects = raw.get("projects")
    if not isinstance(projects, dict):
        raise SystemExit("Config is missing 'projects' object")

    project_data = projects.get(project)
    if project_data is None:
        raise SystemExit(
            f"Project '{project}' not found. Run 'sdeb init {project}' to create it."
        )
    if not isinstance(project_data, dict):
        raise SystemExit(f"Project '{project}' config must be an object")

    return ProjectConfig.from_dict(project_data)


def _prompt_string(label: str, default: str) -> str:
    prefix = _styled(">", "36") + " " if _ansi_enabled() else ""
    label_txt = _styled(label, "1")
    if default:
        prompt = f"{prefix}{label_txt} [{_styled(default, '2')}]: "
    else:
        prompt = f"{prefix}{label_txt}: "
    value = input(prompt).strip()
    return value if value else default


def _prompt_required_string(label: str, default: str) -> str:
    while True:
        value = _prompt_string(label, default).strip()
        if value:
            return value
        print("This value is required.")


def _prompt_int(label: str, default: int) -> int:
    while True:
        prefix = _styled(">", "36") + " " if _ansi_enabled() else ""
        label_txt = _styled(label, "1")
        raw = input(f"{prefix}{label_txt} [{_styled(str(default), '2')}]: ").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            print("Please enter an integer.")


def _prompt_bool(label: str, default: bool) -> bool:
    if _ansi_enabled() and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import select
            import termios
            import tty
        except Exception:
            pass
        else:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            choice = default

            def render() -> str:
                if choice:
                    yes = _styled("Yes", "1;32")
                    no = _styled("No", "2")
                else:
                    yes = _styled("Yes", "2")
                    no = _styled("No", "1;31")
                hint = _styled("(y/n, Enter)", "2")
                return (
                    f"{_styled('>', '36')} {_styled(label, '1')}: {yes} / {no} {hint}"
                )

            try:
                tty.setcbreak(fd)
                while True:
                    sys.stdout.write("\r\x1b[2K" + render())
                    sys.stdout.flush()

                    ch = sys.stdin.read(1)
                    if ch in {"\r", "\n"}:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        return choice
                    if ch in {"y", "Y"}:
                        choice = True
                        continue
                    if ch in {"n", "N"}:
                        choice = False
                        continue
                    if ch in {" ", "\t"}:
                        choice = not choice
                        continue
                    if ch == "\x1b":
                        # Try to read an ANSI arrow sequence without blocking.
                        if not select.select([sys.stdin], [], [], 0.01)[0]:
                            continue
                        ch2 = sys.stdin.read(1)
                        if ch2 != "[":
                            continue
                        if not select.select([sys.stdin], [], [], 0.01)[0]:
                            continue
                        ch3 = sys.stdin.read(1)
                        if ch3 in {"C", "D"}:
                            choice = not choice
                        continue
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    default_str = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} ({default_str}): ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes", "true", "1"}:
            return True
        if raw in {"n", "no", "false", "0"}:
            return False
        print("Please answer y/n.")


def _normalize_mem(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    match = re.fullmatch(r"(\d+)([a-zA-Z]{0,2})", raw)
    if not match:
        return value

    number, unit = match.group(1), match.group(2).lower()
    if unit in {"", "m"}:
        return f"{number}{unit.upper()}" if unit else number
    if unit in {"k", "kb"}:
        return f"{number}K"
    if unit in {"mb"}:
        return f"{number}M"
    if unit in {"g", "gb"}:
        return f"{number}G"
    if unit in {"t", "tb"}:
        return f"{number}T"
    return value


def build_srun_command(cfg: ProjectConfig) -> list[str]:
    if not cfg.partition:
        raise SystemExit("Missing partition. Run 'sdeb init' or pass --partition.")
    if not cfg.account:
        raise SystemExit("Missing account. Run 'sdeb project edit <project>' or pass --account.")

    cmd: list[str] = [
        "srun",
        f"--partition={cfg.partition}",
    ]

    if cfg.node:
        cmd.extend(["-w", cfg.node])

    cmd.append(f"--account={cfg.account}")

    if cfg.time:
        cmd.append(f"--time={cfg.time}")

    if cfg.mem:
        cmd.append(f"--mem={_normalize_mem(cfg.mem)}")

    cmd.append(f"--cpus-per-task={cfg.cpus_per_task}")

    if cfg.gpu:
        gpu_count = cfg.gpus if cfg.gpus > 0 else 1
        cmd.append(f"--gres=gpu:{gpu_count}")

    cmd.append("--pty")
    cmd.extend(shlex.split(cfg.pty_command) if cfg.pty_command else ["bash"])
    return cmd


def _prompt_project_name(default: str) -> str:
    while True:
        project = _prompt_string("Project name", default).strip()
        if project:
            return project
        print("Please enter a project name.")


def _configure_project(name: str, base_cfg: ProjectConfig, title: str) -> ProjectConfig:
    print(_cmd_text(title))
    print(_dim(f"Project: {name}"))
    print()

    account = _prompt_required_string("Account (--account)", base_cfg.account)
    partition = _prompt_string("Partition (--partition)", base_cfg.partition)
    node = _prompt_string("Node (-w) [blank for auto]", base_cfg.node)
    time = _prompt_string("Time (--time)", base_cfg.time)
    mem = _normalize_mem(_prompt_string("Mem (--mem)", base_cfg.mem))
    cpus_per_task = _prompt_int(
        "CPUs per task (--cpus-per-task)", base_cfg.cpus_per_task
    )
    gpu = _prompt_bool("Use GPU?", base_cfg.gpu)
    gpus = 1
    if gpu:
        default_gpus = base_cfg.gpus if base_cfg.gpu else 1
        gpus = _prompt_int("How many GPUs (--gpu)", default_gpus)
        if gpus <= 0:
            gpus = 1

    pty_command = _prompt_string("PTY command", base_cfg.pty_command)

    return ProjectConfig(
        account=account,
        partition=partition,
        node=node,
        time=time,
        mem=mem,
        cpus_per_task=cpus_per_task,
        gpu=gpu,
        gpus=gpus,
        pty_command=pty_command,
    )


def _cmd_project_new(args: argparse.Namespace) -> int:
    path = _config_path()
    raw = _load_raw_config(path)
    projects: dict[str, Any] = raw["projects"]

    project = str(args.name).strip() if args.name else _prompt_project_name(DEFAULT_PROJECT)
    if project in projects:
        raise SystemExit(
            f"Project '{project}' already exists. Use 'sdeb project edit {project}' "
            f"or 'sdeb project copy {project} [new-name]'."
        )

    new_cfg = _configure_project(project, ProjectConfig.from_dict({}), "Create project")

    projects[project] = new_cfg.to_dict()
    raw["active_project"] = project
    raw["projects"] = projects
    _save_raw_config(path, raw)

    print(_ok_text(f"Saved project '{project}'"))
    print(f"Active project is now {_ok_text(project)}")
    print(_dim(f"Config: {path}"))
    return 0


def _cmd_project_edit(args: argparse.Namespace) -> int:
    path = _config_path()
    if not path.exists():
        raise SystemExit(f"No config found at {path}. Run 'sdeb init' first.")

    raw = _load_raw_config(path)
    projects = raw.get("projects")
    if not isinstance(projects, dict):
        raise SystemExit("Config is missing 'projects' object")

    project = str(args.name)
    if project not in projects:
        raise SystemExit(f"Project '{project}' not found. Run 'sdeb project new {project}' first.")

    data = projects.get(project)
    if not isinstance(data, dict):
        raise SystemExit(f"Project '{project}' config must be an object")

    new_cfg = _configure_project(project, ProjectConfig.from_dict(data), "Edit project")
    projects[project] = new_cfg.to_dict()
    raw["active_project"] = project
    raw["projects"] = projects
    _save_raw_config(path, raw)

    print(_ok_text(f"Updated project '{project}'"))
    print(f"Active project is now {_ok_text(project)}")
    print(_dim(f"Config: {path}"))
    return 0


def _copy_name(source: str, projects: dict[str, Any]) -> str:
    base = f"{source}-copy"
    if base not in projects:
        return base
    index = 2
    while f"{base}-{index}" in projects:
        index += 1
    return f"{base}-{index}"


def _cmd_project_copy(args: argparse.Namespace) -> int:
    path = _config_path()
    if not path.exists():
        raise SystemExit(f"No config found at {path}. Run 'sdeb init' first.")

    raw = _load_raw_config(path)
    projects = raw.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise SystemExit(f"No projects found in {path}. Run 'sdeb init' first.")

    source = str(args.source)
    if source not in projects:
        raise SystemExit(f"Project '{source}' not found. Run 'sdeb project list' to see projects.")

    dest = str(args.dest) if args.dest else _copy_name(source, projects)
    if dest in projects:
        raise SystemExit(
            f"Project '{dest}' already exists. Choose another name or edit it with "
            f"'sdeb project edit {dest}'."
        )

    source_data = projects.get(source)
    if not isinstance(source_data, dict):
        raise SystemExit(f"Project '{source}' config must be an object")

    projects[dest] = ProjectConfig.from_dict(source_data).to_dict()
    raw["active_project"] = dest
    raw["projects"] = projects
    _save_raw_config(path, raw)

    print(_ok_text(f"Copied project '{source}' to '{dest}'"))
    print(f"Active project is now {_ok_text(dest)}")
    return 0


def _cmd_project_remove(args: argparse.Namespace) -> int:
    path = _config_path()
    if args.remove_all:
        if not path.exists():
            print(f"No config found at {path}")
            return 0
        if not _prompt_bool(_warn_text(f"Delete all sdeb project settings at {path}?"), False):
            print("Aborted.")
            return 0
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise SystemExit(f"Failed to delete config file: {path}: {exc}") from exc
        print(_ok_text(f"Deleted {path}"))
        return 0

    if not args.name:
        raise SystemExit(
            "Missing project name. Use 'sdeb project remove <name>' or "
            "'sdeb project remove --all'."
        )

    if not path.exists():
        raise SystemExit(f"No config found at {path}. Run 'sdeb init' first.")

    raw = _load_raw_config(path)
    projects = raw.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise SystemExit(f"No projects found in {path}. Run 'sdeb init' first.")

    project = str(args.name)
    if project not in projects:
        raise SystemExit(f"Project '{project}' not found. Run 'sdeb project list' to see projects.")

    if not _prompt_bool(_warn_text(f"Remove project '{project}'?"), False):
        print("Aborted.")
        return 0

    del projects[project]
    active = str(raw.get("active_project") or "")
    if active == project:
        raw["active_project"] = sorted(str(name) for name in projects.keys())[0] if projects else ""
    raw["projects"] = projects
    _save_raw_config(path, raw)

    print(_ok_text(f"Removed project '{project}'"))
    if raw["active_project"]:
        print(f"Active project is now {_ok_text(str(raw['active_project']))}")
        print()
        _print_projects(raw, path, title="Remaining projects")
    else:
        print("No projects remain. Run 'sdeb init' to create one.")
    return 0


def _cmd_project_use(args: argparse.Namespace) -> int:
    path = _config_path()
    if not path.exists():
        raise SystemExit(f"No config found at {path}. Run 'sdeb init' first.")

    raw = _load_raw_config(path)
    projects = raw.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise SystemExit(f"No projects found in {path}. Run 'sdeb init' first.")

    project = str(args.name)
    if project not in projects:
        raise SystemExit(f"Project '{project}' not found. Run 'sdeb project list' to see projects.")

    raw["active_project"] = project
    _save_raw_config(path, raw)
    print(f"Active project is now {_ok_text(project)}")
    return 0


def _cmd_project_list(args: argparse.Namespace) -> int:
    del args
    path = _config_path()
    raw = _load_raw_config(path)
    _print_projects(raw, path)
    return 0


def _print_projects(raw: dict[str, Any], path: Path, title: str = "Projects") -> None:
    active = str(raw.get("active_project") or "")
    projects = raw.get("projects")
    if not isinstance(projects, dict) or not projects:
        print(_cmd_text(title))
        print()
        print("No projects found.")
        print(_dim("Run 'sdeb init' to create one."))
        print(_dim(f"Config: {path}"))
        return

    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for name in sorted(str(name) for name in projects.keys()):
        data = projects.get(name)
        cfg = ProjectConfig.from_dict(data) if isinstance(data, dict) else ProjectConfig.from_dict({})
        rows.append(
            (
                "*" if name == active else "",
                name,
                cfg.partition,
                cfg.node if cfg.node else "auto",
                cfg.time,
                cfg.mem,
                str(cfg.cpus_per_task),
                str(cfg.gpus if cfg.gpus > 0 else 1) if cfg.gpu else "no",
            )
        )

    headers = ("active", "name", "partition", "node", "time", "mem", "cpus", "gpu")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def fmt(row: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    print(_cmd_text(title))
    print()
    print("  " + _bold(fmt(headers)))
    for row in rows:
        marker_raw = row[0].ljust(widths[0])
        name_raw = row[1].ljust(widths[1])
        marker = _ok_text(marker_raw) if row[0] else marker_raw
        name = _ok_text(name_raw) if row[1] == active else _bold(name_raw)
        rest = "  ".join(row[index].ljust(widths[index]) for index in range(2, len(row)))
        print("  " + "  ".join((marker, name, rest)))

    print()
    if active:
        print(f"Active project: {_ok_text(active)}")
    else:
        print(_warn_text("No active project set."))
        print(_dim("Run 'sdeb project use <name>' to choose one."))
    print(_dim(f"Config: {path}"))


def _cmd_project_help(args: argparse.Namespace) -> int:
    del args
    _print_project_help()
    return 0


def _cmd_help(args: argparse.Namespace) -> int:
    del args
    _print_main_help()
    return 0


def _cmd_legacy_purge(args: argparse.Namespace) -> int:
    args.remove_all = True
    args.name = None
    return _cmd_project_remove(args)


def _cmd_legacy_projects(args: argparse.Namespace) -> int:
    return _cmd_project_list(args)


def _cmd_legacy_use(args: argparse.Namespace) -> int:
    args.name = args.project
    return _cmd_project_use(args)


def _apply_overrides(cfg: ProjectConfig, args: argparse.Namespace) -> ProjectConfig:
    def override_str(current: str, value: str | None) -> str:
        return current if value is None else value

    def override_int(current: int, value: int | None) -> int:
        return current if value is None else value

    gpu = cfg.gpu
    gpus = cfg.gpus
    if args.cpu:
        gpu = False
        gpus = 1
    elif args.gpu is not None:
        if args.gpu <= 0:
            raise SystemExit("--gpu must be 1 or greater. Use --cpu for CPU-only jobs.")
        gpu = True
        gpus = args.gpu

    return ProjectConfig(
        account=override_str(cfg.account, args.account),
        partition=override_str(cfg.partition, args.partition),
        node=override_str(cfg.node, args.node),
        time=override_str(cfg.time, args.time),
        mem=_normalize_mem(override_str(cfg.mem, args.mem)),
        cpus_per_task=override_int(cfg.cpus_per_task, args.cpus_per_task),
        gpu=gpu,
        gpus=gpus,
        pty_command=override_str(cfg.pty_command, args.pty_command),
    )


def _cmd_run(args: argparse.Namespace) -> int:
    path = _config_path()
    if not path.exists():
        raise SystemExit(f"No config found at {path}. Run 'sdeb init' first.")
    raw = _load_raw_config(path)

    project = args.project or str(raw.get("active_project") or "")
    if not project:
        raise SystemExit("No active project set. Run 'sdeb project list' or 'sdeb init'.")
    cfg = _get_project_config(raw, project)
    cfg = _apply_overrides(cfg, args)

    cmd = build_srun_command(cfg)
    if args.dry_run:
        print(shlex.join(cmd))
        return 0

    print(shlex.join(cmd), file=sys.stderr)
    sys.stderr.flush()
    os.execvp(cmd[0], cmd)
    raise AssertionError("execvp should not return")


def _help_row(command: str, description: str, *, warn: bool = False) -> str:
    padded = command.ljust(32)
    command_text = _warn_text(padded) if warn else _cmd_text(padded)
    return f"  {command_text} {description}"


def _print_main_help() -> None:
    print(_cmd_text("sdeb"))
    print("Run SLURM shells with saved project defaults.")
    print()
    print(_bold("Usage"))
    print(f"  {_cmd_text('sdeb')} [run options]")
    print(f"  {_cmd_text('sdeb init')} [name]")
    print(f"  {_cmd_text('sdeb project')} <command>")
    print()
    print(_bold("Common Commands"))
    print(_help_row("sdeb init [name]", "Create a new project from default settings"))
    print(_help_row("sdeb", "Run srun with the active project"))
    print(_help_row("sdeb --dry-run", "Preview the srun command"))
    print(_help_row("sdeb project list", "Show saved projects"))
    print(_help_row("sdeb project use <name>", "Switch active project"))
    print(_help_row("sdeb project edit <name>", "Edit an existing project"))
    print()
    print(_bold("Project Commands"))
    print(_help_row("sdeb project new [name]", "Create a project from code defaults"))
    print(_help_row("sdeb project copy <src> [dst]", "Copy a project config"))
    print(_help_row("sdeb project remove <name>", "Remove one project"))
    print(_help_row("sdeb project remove --all", "Remove all project settings", warn=True))
    print()
    print(_bold("Run Options"))
    print(_help_row("--project <name>", "Use a project without switching active project"))
    print(_help_row("--partition <name>", "Override SLURM partition"))
    print(_help_row("--time HH:MM:SS", "Override time limit"))
    print(_help_row("--mem 8G", "Override memory"))
    print(_help_row("--cpus-per-task N", "Override CPU count"))
    print(_help_row("--cpu", "Force a CPU-only job"))
    print(_help_row("--gpu [N]", "Force a GPU job; default N is 1"))
    print(_help_row("--dry-run", "Print command without running it"))
    print()
    print(_bold("Examples"))
    print(f"  {_cmd_text('sdeb init gpu-test')}")
    print(f"  {_cmd_text('sdeb project list')}")
    print(f"  {_cmd_text('sdeb project copy gpu-test gpu-long')}")
    print(f"  {_cmd_text('sdeb --project gpu-test --gpu 2 --dry-run')}")
    print()
    print(_dim("Use 'sdeb project help' for project lifecycle commands."))


def _print_project_help() -> None:
    print(_cmd_text("sdeb project"))
    print("Manage saved SLURM project defaults.")
    print()
    print(_bold("Usage"))
    print(f"  {_cmd_text('sdeb project')} <command>")
    print()
    print(_bold("Commands"))
    print(_help_row("list", "List projects and show the active one"))
    print(_help_row("new [name]", "Create a new project from defaults"))
    print(_help_row("edit <name>", "Edit an existing project"))
    print(_help_row("copy <source> [dest]", "Copy a project config"))
    print(_help_row("use <name>", "Make a project active"))
    print(_help_row("remove <name>", "Remove one project"))
    print(_help_row("remove --all", "Remove all project settings", warn=True))
    print()
    print(_bold("Recommended Flow"))
    print(f"  1. {_cmd_text('sdeb init myproj')}")
    print(f"  2. {_cmd_text('sdeb project list')}")
    print(f"  3. {_cmd_text('sdeb')}")
    print(f"  4. {_cmd_text('sdeb project edit myproj')}")
    print()
    print(_bold("Safety"))
    print(f"  {_warn_text('remove')} asks for confirmation.")
    print(f"  {_warn_text('remove --all')} asks for confirmation and deletes the config file.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdeb",
        description="Interactive helper for spawning SLURM shells via srun.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sdeb {__version__}",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    help_parser = subparsers.add_parser("help", help="Show task-oriented help")
    help_parser.set_defaults(_handler=_cmd_help)

    init_parser = subparsers.add_parser(
        "init",
        help="Create a new project from default settings",
    )
    init_parser.add_argument("name", nargs="?", help="Project name")
    init_parser.set_defaults(_handler=_cmd_project_new)

    project_parser = subparsers.add_parser(
        "project",
        help="Manage saved project settings",
    )
    project_parser.set_defaults(_handler=_cmd_project_help)
    project_subparsers = project_parser.add_subparsers(dest="project_command")

    project_help_parser = project_subparsers.add_parser(
        "help",
        help="Show project command help",
    )
    project_help_parser.set_defaults(_handler=_cmd_project_help)

    project_list_parser = project_subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List configured projects",
    )
    project_list_parser.set_defaults(_handler=_cmd_project_list)

    project_new_parser = project_subparsers.add_parser(
        "new",
        help="Create a new project from default settings",
    )
    project_new_parser.add_argument("name", nargs="?", help="Project name")
    project_new_parser.set_defaults(_handler=_cmd_project_new)

    project_edit_parser = project_subparsers.add_parser(
        "edit",
        help="Edit an existing project",
    )
    project_edit_parser.add_argument("name", help="Project name")
    project_edit_parser.set_defaults(_handler=_cmd_project_edit)

    project_copy_parser = project_subparsers.add_parser(
        "copy",
        help="Copy an existing project config",
    )
    project_copy_parser.add_argument("source", help="Project to copy")
    project_copy_parser.add_argument("dest", nargs="?", help="New project name")
    project_copy_parser.set_defaults(_handler=_cmd_project_copy)

    project_use_parser = project_subparsers.add_parser(
        "use",
        help="Switch the active project",
    )
    project_use_parser.add_argument("name", help="Project name")
    project_use_parser.set_defaults(_handler=_cmd_project_use)

    project_remove_parser = project_subparsers.add_parser(
        "remove",
        aliases=["rm"],
        help="Remove one project or all settings",
    )
    project_remove_parser.add_argument("name", nargs="?", help="Project name")
    project_remove_parser.add_argument(
        "--all",
        action="store_true",
        dest="remove_all",
        help="Remove all project settings",
    )
    project_remove_parser.set_defaults(_handler=_cmd_project_remove, remove_all=False)

    purge_parser = subparsers.add_parser(
        "purge",
        help="Alias for 'project remove --all'",
    )
    purge_parser.set_defaults(_handler=_cmd_legacy_purge)

    clean_parser = subparsers.add_parser(
        "clean",
        help="Alias for 'project remove --all'",
    )
    clean_parser.set_defaults(_handler=_cmd_legacy_purge)

    projects_parser = subparsers.add_parser(
        "projects",
        help="Alias for 'project list'",
    )
    projects_parser.set_defaults(_handler=_cmd_legacy_projects)

    use_parser = subparsers.add_parser(
        "use",
        help="Alias for 'project use'",
    )
    use_parser.add_argument("project", help="Project name to activate")
    use_parser.set_defaults(_handler=_cmd_legacy_use)

    def add_run_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", help="Project to use (defaults to active project)")
        p.add_argument("--partition", help="SLURM partition")
        p.add_argument("--node", help="Node list passed to -w")
        p.add_argument("--account", help="SLURM account")
        p.add_argument("--time", help="Time limit, e.g. 00:20:00")
        p.add_argument("--mem", help="Memory, e.g. 8G")
        p.add_argument("--cpus-per-task", type=int, dest="cpus_per_task")
        gpu_group = p.add_mutually_exclusive_group()
        gpu_group.add_argument(
            "--cpu",
            action="store_true",
            help="Force a CPU-only job for this run",
        )
        gpu_group.add_argument(
            "--gpu",
            nargs="?",
            const=1,
            type=int,
            metavar="N",
            help="Force a GPU job; defaults to 1 GPU when N is omitted",
        )
        p.add_argument(
            "--pty-command",
            help="Command to run under --pty (default: bash)",
        )
        p.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the resulting srun command and exit",
        )

    add_run_flags(parser)
    parser.set_defaults(_handler=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    ns = parser.parse_args(argv)
    handler = getattr(ns, "_handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(ns))


if __name__ == "__main__":
    raise SystemExit(main())
