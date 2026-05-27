# copilot-session

> Per-repo session persistence for [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/use-copilot-agents/use-copilot-cli).

Every time you `cd` into a git repo and run `copilot`, this tool automatically resumes the last session you had in that repo — no flags, no extra steps.

Works on **Linux**, **macOS**, and **Windows**.

---

## Why

By default, every `copilot` invocation starts a brand-new session. If you close your terminal and come back to a project the next day, all context is lost.

`copilot-session` fixes this by storing a session UUID in `.git/copilot-session` and passing `--session-id <uuid>` to the Copilot CLI on every startup. Each git repo gets its own independent, persistent session.

---

## Requirements

- Python 3.8+
- [GitHub Copilot CLI](https://docs.github.com/copilot/how-tos/use-copilot-agents/use-copilot-cli) installed

---

## Installation

```bash
# Clone or copy the project, then install
pip install --editable ~/copilot-session
```

Once published to PyPI:

```bash
pip install copilot-session
```

### One-time setup

After installing the package, run setup once to activate the wrapper:

```bash
copilot-session setup
```

This renames your real `copilot` binary to `copilot-real` (or `copilot-real.exe` on Windows)
and installs a thin Python wrapper in its place. From this point on, just use `copilot` as normal.

---

## Usage

```bash
# First time in a repo
cd ~/my-project
copilot
# [copilot-session] New session 4f1a2b3c (my-project)

# Next time — context is restored automatically
cd ~/my-project
copilot
# [copilot-session] Resuming session 4f1a2b3c (my-project)

# Different repo → separate session
cd ~/other-project
copilot
# [copilot-session] New session 9e8d7c6b (other-project)
```

All flags and options you pass to `copilot` are forwarded unchanged to the real binary:

```bash
copilot --autopilot --allow-all --model gpt-4   # works as expected
```

### Start a fresh session in the current repo

```bash
copilot-session reset
```

### Bypass auto-resume (manual control)

Passing any of the following flags skips the session logic entirely and passes
through directly to the real binary:

```bash
copilot --resume          # use Copilot's own session picker
copilot --session-id <id> # specify a session explicitly
copilot --continue        # resume the most recent session
copilot --clear           # start a fresh session
copilot -p "..."          # non-interactive prompt mode
```

---

## Commands

| Command | Description |
|---|---|
| `copilot-session setup` | Install the wrapper (one-time) |
| `copilot-session teardown` | Remove the wrapper and restore the original binary |
| `copilot-session status` | Show platform, wrapper state, and binary paths |
| `copilot-session reset` | Delete the session file for the current repo (next run starts fresh) |

---

## How it works

```
copilot  (wrapper)
  │
  ├─ finds git root of cwd
  ├─ reads/creates  .git/copilot-session  (UUID, never committed)
  └─ launches copilot-real --session-id <uuid> [your args]
```

- Session files live inside `.git/` so they are never accidentally committed.
- Each git repository has its own independent session.
- Outside a git repo, the wrapper passes through to the real binary unchanged.
- All flags and options are forwarded verbatim to the real binary.

### Platform details

| | Linux | macOS | Windows |
|---|---|---|---|
| Wrapper file | `copilot` (shebang script) | `copilot` (shebang script) | `copilot.cmd` (batch file) |
| Real binary | `copilot-real` | `copilot-real` | `copilot-real.exe` |
| Process launch | `os.execv` (true replace) | `os.execv` (true replace) | `subprocess` + exit code |

### Project structure

```
copilot-session/
├── pyproject.toml
├── README.md
└── src/copilot_session/
    ├── wrapper.py   # core session logic (cross-platform)
    └── cli.py       # copilot-session management commands
```

---

## Copilot updates

**Automatic updates are safe.** When `copilot update` runs (or the CLI auto-updates
on startup), the updater uses its own executable path (`copilot-real`) to write the
new binary — the wrapper is untouched.

If you ever manually reinstall the Copilot CLI (e.g. re-download the binary), the
wrapper may be overwritten. To repair it:

```bash
copilot-session setup
```

On **Linux/macOS**, a startup guard in `~/.bashrc` detects this automatically and
re-runs setup the next time you open a terminal, so no manual action is needed.

---

## Uninstall

```bash
copilot-session teardown   # restores the original copilot binary
pip uninstall copilot-session
```

---

## License

MIT
