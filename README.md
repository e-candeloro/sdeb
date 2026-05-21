## sdeb

Simple interactive helper for spawning SLURM shells via `srun`.

### Install globally

With `pipx` (recommended if you already use it):

```bash
pipx install .
```

With `uv` tool:

```bash
uv tool install -e .
```

### Usage

First, set defaults (saved in `~/.config/sdeb/config.json`):

```bash
sdeb set
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

Preview the command without running it:

```bash
sdeb --dry-run
```
