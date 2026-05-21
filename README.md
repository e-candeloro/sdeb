## sdeb

Simple interactive helper for spawning SLURM shells via `srun`.

### Install globally

Without cloning the repo:

With `uv`:

```bash
uv tool install git+https://github.com/e-candeloro/sdeb
```

With `pipx`:

```bash
pipx install git+https://github.com/e-candeloro/sdeb
```

Upgrade:

```bash
uv tool upgrade sdeb
pipx reinstall sdeb
```

Development install (from a local checkout):

```bash
pipx install .
uv tool install -e .
```

### Usage

First, set defaults (saved in `~/.config/sdeb/config.json` or `$XDG_CONFIG_HOME/sdeb/config.json`).

This supports multiple named projects; the first prompt is the project name.

```bash
sdeb set
```

Create a new project config (example):

```bash
sdeb set --project myproj
# then type "myproj" at the first prompt (Project)
```

List projects (active project is highlighted):

```bash
sdeb projects
```

Switch which project is active by default:

```bash
sdeb use myproj
```

Then spawn a SLURM `bash` using those defaults:

```bash
sdeb
```

Override only what you need for a single run:

```bash
sdeb --time 01:00:00
sdeb --partition all_serial --no-gpu
sdeb --gpus 2
sdeb --node ailb-login-03 --cpus-per-task 16
```

Run using a specific (non-active) project without switching:

```bash
sdeb --project myproj
```

Preview the command without running it:

```bash
sdeb --dry-run
```

Delete/reset your saved config:

```bash
sdeb purge
# alias:
sdeb clean
```
