# ai-session-manager

> Per-project session persistence for AI CLI tools.

`ai-session-manager` adds automatic project-scoped resume behavior to supported AI CLIs so you can leave a project and come back without manually reopening the right conversation.

Tested on **Linux** and **Windows**.

Wrappers live in a dedicated directory placed before your tools in `PATH`. Setup leaves installed CLI binaries and their symlinks intact, so tools can still update normally.

---

## Why

Most AI CLIs support sessions, but they do not all resume the same way and they do not all make project-scoped resume automatic. This project adds one consistent wrapper layer across tools.

Today it supports:

| Tool | Auto-resume behavior |
|---|---|
| `agy` | Starts normally on first run, then stores/discovers a native conversation ID and resumes with `agy --conversation <id>` |
| `copilot` | Stores a stable session UUID and launches `copilot --session-id <uuid>` |
| `claude` | Stores a managed session UUID, starts with `claude --session-id <uuid>`, then resumes with `claude -r <uuid>` |
| `codex` | Starts normally on first run, then stores/discovers the native session ID and resumes with `codex resume <id>` |

Project-scoped state lives in:

- `.ai-session-manager/` inside the project root, whether it is a git repo or a plain folder

Existing state is still recognized and migrated from:

- `.git/ai-session-manager/`

Copilot legacy state is also recognized and migrated from:

- `.git/copilot-session`
- `.copilot-session`

---

## Requirements

- Python 3.8+
- One or more supported CLIs installed: Antigravity, Copilot, Claude Code, or Codex CLI

---

## Installation

```bash
pip install --editable ~/ai-session-manager
```

Once published:

```bash
pip install ai-session-manager
```

---

## Setup

Install wrappers for every supported tool found in `PATH`:

```bash
ai-session-manager setup
```

Or target specific tools:

```bash
ai-session-manager setup agy copilot claude codex
```

Setup prints the wrapper location and the shell command needed to activate it. On Linux and macOS, the default location is `~/.local/share/ai-session-manager/bin` (or `$XDG_DATA_HOME/ai-session-manager/bin`). Add it **before** your native tool directories in your shell profile:

```bash
export PATH="$HOME/.local/share/ai-session-manager/bin:$PATH"
```

Restart your shell, or run `hash -r` in Bash, then keep using the original tool commands. Run `ai-session-manager status` to check that the wrappers are active.

On Windows, add `%LOCALAPPDATA%\ai-session-manager\bin` before the tool directories in your user `PATH` and open a new terminal. Setup prints the exact directory. Wrappers use the Python interpreter that ran setup; rerun setup if you move or replace that Python environment.

Set `AI_SESSION_MANAGER_BIN_DIR` to use a different wrapper directory. Keep that setting when running setup, status, or teardown. Existing unrelated files and symlinks in that directory are never overwritten.

### Migrating from a previous installation

Older releases renamed native binaries to `<tool>-real`. Before installing the new wrappers, restore those binaries:

```bash
ai-session-manager teardown
ai-session-manager setup
```

Then activate the new wrapper directory in `PATH`. Project session state is preserved. If the legacy real binary is missing, reinstall the affected native tool first. Teardown refuses to overwrite a native tool that has already been reinstalled.

---

## Usage

### Copilot

```bash
cd ~/my-project
copilot
# [ai-session-manager] New session 4f1a2b3c-... (my-project)

cd ~/my-project
copilot
# [ai-session-manager] Resuming session 4f1a2b3c-... (my-project)
```

### AGY

```bash
agy
# [ai-session-manager] Starting new Antigravity CLI session (my-project)

agy
# [ai-session-manager] Resuming session 123e4567-... (my-project)
```

### Claude

```bash
claude
# [ai-session-manager] New session 4f1a2b3c-... (my-project)

claude
# [ai-session-manager] Resuming session 4f1a2b3c-... (my-project)
```

### Codex

```bash
codex
# [ai-session-manager] Starting new Codex session (my-project)

codex
# [ai-session-manager] Resuming session 019e94b3-... (my-project)
```

Supported tools are still fully usable with their own native session commands. If you pass an explicit resume or session-management flag/subcommand, the wrapper gets out of the way.

For example:

```bash
agy --conversation 123e4567-e89b-12d3-a456-426614174000
copilot --resume
claude -r my-session
codex resume --last
```

### Start fresh in the current project

```bash
ai-session-manager reset
```

Or reset one tool only:

```bash
ai-session-manager reset claude
```

---

## Commands

| Command | Description |
|---|---|
| `ai-session-manager --version` | Show the installed package version |
| `ai-session-manager setup [tools...]` | Install wrappers for all detected or selected tools |
| `ai-session-manager teardown [tools...]` | Remove dedicated wrappers, or restore legacy renamed binaries |
| `ai-session-manager status [tools...]` | Show paths, saved session IDs, and actionable installation/state problems |
| `ai-session-manager reset [tools...]` | Delete persisted wrapper state for the current project |

---

## State layout

```text
project root:
  .ai-session-manager/
    copilot.json
    claude.json
    codex.json
    agy.json
```

Copilot and Claude store an exact managed session identifier in their state files from the first launch.

AGY and Codex store the tool's own native conversation/session identifier once the wrapper can discover it from local history after a successful run. If no exact project session can be found, they start fresh. They never automatically resume an unverified latest session. A missing Claude transcript is started with its managed session ID rather than resuming a different conversation.

State is written atomically. Invalid JSON or incompatible state stops the launch with a recovery message and leaves the original file intact. Back up that file if needed, then run `ai-session-manager reset <tool>` to start fresh.

Only one managed session per tool and project may run at a time. A second launch or reset reports that the session is busy. Different tools and different projects can run independently. Lock files remain in the state directory; the operating system releases the lock when its owning process exits. Native explicit session commands bypass this management, so you can still open an independent conversation intentionally.

`status` is read-only and returns a nonzero exit code for detected problems, including wrappers hidden by another PATH entry, missing native tools, invalid state, and missing saved transcripts where they can be checked. Fix the reported problem and rerun `status`.

### Platform details

| | Linux | macOS | Windows |
|---|---|---|---|
| Wrapper file | tool name (shell script) | tool name (shell script) | tool `.cmd` wrapper |
| Native binary | Unchanged | Unchanged | Unchanged |
| Managed process launch | Subprocess held under a project lock | Subprocess held under a project lock | Subprocess held under a project lock |

### Project structure

```text
ai-session-manager/
├── pyproject.toml
├── README.md
└── src/
    ├── ai_session_manager/
    │   ├── wrapper.py
    │   ├── installation.py
    │   └── cli.py
```

---

## Reinstalling a tool CLI

Native tools can be updated or reinstalled in their normal locations. Wrappers discover the current native executable through `PATH`, skipping other session-manager wrappers. If the wrapper is no longer active, inspect the PATH order:

```bash
ai-session-manager status copilot
```

---

## Uninstall

```bash
ai-session-manager teardown
pip uninstall ai-session-manager
```

Remove the wrapper directory from your shell profile or Windows user `PATH` if you no longer need it.

## Development

The test suite uses the standard library and temporary directories; it does not need installed AI CLIs:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

On PowerShell, set `$env:PYTHONPATH = "src"` before running the Python command. CI runs on Linux and Windows with Python 3.8 and 3.12.

## License

MIT
