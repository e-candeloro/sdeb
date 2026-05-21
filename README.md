# sdeb

[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://docs.astral.sh/uv/)
[![SLURM](https://img.shields.io/badge/SLURM-compatible-green?logo=linux&logoColor=white)](https://slurm.schedmd.com/)

> Save SLURM `srun` defaults per project and launch interactive shells without retyping long commands.

`sdeb` is a small CLI for interactive SLURM sessions. It stores the account, partition, node, time, memory, CPU count, GPU request, and PTY command you normally pass to `srun`, then reuses them with one command.

---

## Why sdeb?

Interactive SLURM commands get long quickly:

```bash
srun --partition=debug -w compute-01 --account=my_account --time=00:20:00 --mem=8G --cpus-per-task=8 --gres=gpu:1 --pty bash
```

With `sdeb`, save that once as a project:

```bash
sdeb init myproj
sdeb
```

Then override only what changes:

```bash
sdeb --time 01:00:00
sdeb --gpu 2
sdeb --cpu
```

---

## Install

No root. No `sudo`. Works anywhere Python can install command-line tools into your user environment.

### uv recommended

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh  # install uv itself once
uv tool install git+https://github.com/e-candeloro/sdeb
```

If `uv` warns that the tool directory is not on `PATH`, either run:

```bash
uv tool update-shell
```

or install into a known user bin directory that is already on `PATH`:

```bash
UV_TOOL_BIN_DIR="$HOME/.local/bin" uv tool install git+https://github.com/e-candeloro/sdeb
```

When installing from a Snap-packaged editor terminal, `$HOME` can point inside the Snap sandbox. In that case, install from a normal terminal or set `UV_TOOL_BIN_DIR` to your real user bin directory, for example `/home/$USER/.local/bin`.

Upgrade later:

```bash
uv tool upgrade sdeb
```

### pipx

```bash
python3 -m pip install --user pipx
pipx install git+https://github.com/e-candeloro/sdeb
```

Upgrade later:

```bash
pipx upgrade sdeb
```

---

## Quick Start

Create a project. The SLURM account is required.

```bash
sdeb init myproj
```

Run the active project:

```bash
sdeb
```

Preview the exact `srun` command without launching it:

```bash
sdeb --dry-run
```

Get task-oriented help:

```bash
sdeb help
sdeb project help
```

Saved projects live in `~/.config/sdeb/config.json` or `$XDG_CONFIG_HOME/sdeb/config.json`.

---

## Project Commands

```bash
sdeb project list                    # list projects; active project is marked with '*'
sdeb project new gpu-test            # create from built-in defaults
sdeb project edit myproj             # edit an existing project
sdeb project copy myproj             # creates myproj-copy, or myproj-copy-2 if needed
sdeb project copy myproj long-job    # copy to an explicit name
sdeb project use myproj              # switch active project
sdeb project remove myproj           # remove one project, with confirmation
sdeb project remove --all            # remove all settings, with confirmation
```

Convenience aliases:

```bash
sdeb projects       # same as: sdeb project list
sdeb use myproj     # same as: sdeb project use myproj
sdeb purge          # same as: sdeb project remove --all
sdeb clean          # same as: sdeb project remove --all
```

---

## Run Overrides

Use a project without switching the active project:

```bash
sdeb --project myproj
```

Override SLURM resources for a single run:

```bash
sdeb --partition debug
sdeb --node compute-01
sdeb --account my_account
sdeb --time 01:00:00
sdeb --mem 16G
sdeb --cpus-per-task 16
```

Choose CPU or GPU mode for a single run:

```bash
sdeb --cpu       # force CPU-only; no --gres is emitted
sdeb --gpu       # force one GPU; emits --gres=gpu:1
sdeb --gpu 2     # force two GPUs; emits --gres=gpu:2
```

Invalid combinations are rejected:

```bash
sdeb --cpu --gpu 2
sdeb --gpu 0
```

Show the installed version:

```bash
sdeb --version
```

---

## Generated SLURM Command

A project configured with account `my_account`, partition `debug`, node `compute-01`, 20 minutes, 8 GB RAM, 8 CPUs, and one GPU generates:

```bash
srun --partition=debug -w compute-01 --account=my_account --time=00:20:00 --mem=8G --cpus-per-task=8 --gres=gpu:1 --pty bash
```

CPU override removes the GPU request:

```bash
sdeb --cpu --dry-run
# srun --partition=debug -w compute-01 --account=my_account --time=00:20:00 --mem=8G --cpus-per-task=8 --pty bash
```

---

## Safety

- `sdeb project remove <name>` asks before deleting a project.
- If the active project is removed, `sdeb` automatically activates another remaining project and lists what is left.
- `sdeb project remove --all`, `sdeb purge`, and `sdeb clean` ask before deleting the config file.
- `sdeb --dry-run` prints the command and never launches SLURM.

---

## Development

```bash
git clone https://github.com/e-candeloro/sdeb
cd sdeb
uv tool install -e .
sdeb help
```

Run from a checkout without installing:

```bash
PYTHONPATH=src python3 -m sdeb.cli help
```

Use a temporary config while testing:

```bash
XDG_CONFIG_HOME=/tmp/sdeb-test PYTHONPATH=src python3 -m sdeb.cli init test
XDG_CONFIG_HOME=/tmp/sdeb-test PYTHONPATH=src python3 -m sdeb.cli --dry-run
```

---

## Project Layout

```text
src/sdeb/
├── __init__.py  # package version
└── cli.py       # argument parsing, config, prompts, and srun command building
README.md        # user documentation
pyproject.toml   # package metadata and console script
```
