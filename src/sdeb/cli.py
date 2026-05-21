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
    term = os.environ.get("TERM", "")
    if not term or term == "dumb":
        return False
    return sys.stdout.isatty()


def _styled(text: str, sgr: str) -> str:
    if not _ansi_enabled():
        return text
    return f"\x1b[{sgr}m{text}\x1b[0m"


def _config_path() -> Path:
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_home).expanduser() if xdg_home else (Path.home() / ".config")
    return base / "sdeb" / "config.json"


def _load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "active_project": DEFAULT_PROJECT,
            "projects": {DEFAULT_PROJECT: dict(DEFAULTS)},
        }

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
        active_project = DEFAULT_PROJECT

    if DEFAULT_PROJECT not in projects:
        projects[DEFAULT_PROJECT] = dict(DEFAULTS)

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
            f"Project '{project}' not found in config. Run 'sdeb set' first."
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
        raise SystemExit("Missing partition. Run 'sdeb set' or pass --partition.")

    cmd: list[str] = [
        "srun",
        f"--partition={cfg.partition}",
    ]

    if cfg.node:
        cmd.extend(["-w", cfg.node])

    if cfg.account:
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


def _cmd_set(args: argparse.Namespace) -> int:
    path = _config_path()
    raw = _load_raw_config(path)

    active_project = raw["active_project"]
    projects: dict[str, Any] = raw["projects"]

    default_project = args.project or str(active_project)
    project = _prompt_string("Project", default_project)

    base_cfg: ProjectConfig
    if project in projects and isinstance(projects[project], dict):
        base_cfg = ProjectConfig.from_dict(projects[project])
    else:
        base_cfg = ProjectConfig.from_dict(projects.get(active_project, {}))

    new_cfg = ProjectConfig(
        account=_prompt_string("Account (--account)", base_cfg.account),
        partition=_prompt_string("Partition (--partition)", base_cfg.partition),
        node=_prompt_string("Node (-w) [blank for auto]", ""),
        time=_prompt_string("Time (--time)", base_cfg.time),
        mem=_normalize_mem(_prompt_string("Mem (--mem)", base_cfg.mem)),
        cpus_per_task=_prompt_int(
            "CPUs per task (--cpus-per-task)", base_cfg.cpus_per_task
        ),
        gpu=_prompt_bool("Use GPU?", base_cfg.gpu),
        gpus=1,
        pty_command=_prompt_string("PTY command", base_cfg.pty_command),
    )

    if new_cfg.gpu:
        default_gpus = base_cfg.gpus if base_cfg.gpu else 1
        gpus = _prompt_int("How many GPUs (--gpus)", default_gpus)
        if gpus <= 0:
            gpus = 1
        new_cfg = ProjectConfig(
            account=new_cfg.account,
            partition=new_cfg.partition,
            node=new_cfg.node,
            time=new_cfg.time,
            mem=new_cfg.mem,
            cpus_per_task=new_cfg.cpus_per_task,
            gpu=new_cfg.gpu,
            gpus=gpus,
            pty_command=new_cfg.pty_command,
        )

    projects[project] = new_cfg.to_dict()
    raw["active_project"] = project
    raw["projects"] = projects

    _save_raw_config(path, raw)

    print(f"Saved project '{project}' to {path}")
    print(f"Active project is now '{project}'")
    return 0


def _apply_overrides(cfg: ProjectConfig, args: argparse.Namespace) -> ProjectConfig:
    def override_str(current: str, value: str | None) -> str:
        return current if value is None else value

    def override_int(current: int, value: int | None) -> int:
        return current if value is None else value

    def override_bool(current: bool, value: bool | None) -> bool:
        return current if value is None else value

    gpu = override_bool(cfg.gpu, args.gpu)
    gpus = override_int(cfg.gpus, getattr(args, "gpus", None))
    if getattr(args, "gpus", None) is not None:
        if args.gpus <= 0:
            gpu = False
        else:
            gpu = True
            gpus = args.gpus

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
        raise SystemExit(f"No config found at {path}. Run 'sdeb set' first.")
    raw = _load_raw_config(path)

    project = args.project or str(raw.get("active_project") or DEFAULT_PROJECT)
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdeb",
        description="Interactive helper for spawning SLURM shells via srun.",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    set_parser = subparsers.add_parser(
        "set", help="Interactively set defaults for a project"
    )
    set_parser.add_argument(
        "--project",
        help="Project name to prefill (you can still change it interactively)",
    )
    set_parser.set_defaults(_handler=_cmd_set)

    def add_run_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", help="Project to use (defaults to active project)")
        p.add_argument("--partition", help="SLURM partition")
        p.add_argument("--node", help="Node list passed to -w")
        p.add_argument("--account", help="SLURM account")
        p.add_argument("--time", help="Time limit, e.g. 00:20:00")
        p.add_argument("--mem", help="Memory, e.g. 8G")
        p.add_argument("--cpus-per-task", type=int, dest="cpus_per_task")
        p.add_argument(
            "--gpu",
            action=argparse.BooleanOptionalAction,
            default=None,
            help="Enable/disable requesting GPUs (see also --gpus)",
        )
        p.add_argument(
            "--gpus",
            type=int,
            help="Number of GPUs to request (implies --gpu). Use 0 for none.",
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
