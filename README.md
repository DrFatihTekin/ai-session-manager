# ai-session-manager

> Per-project session persistence for AI CLI tools.

`ai-session-manager` adds automatic project-scoped resume behavior to supported AI CLIs so you can leave a project and come back without manually reopening the right conversation.

Works on **Linux**, **macOS**, and **Windows**.

> [!WARNING]
> This tool renames installed CLI binaries and replaces them with wrapper scripts. Use it at your own risk, and make sure you understand how to restore the original binaries with `ai-session-manager teardown`.

---

## Why

Most AI CLIs support sessions, but they do not all resume the same way and they do not all make project-scoped resume automatic. This project adds one consistent wrapper layer across tools.

Today it supports:

| Tool | Auto-resume behavior |
|---|---|
| `agy` | Starts normally on first run, then stores/discovers a native conversation ID and resumes with `agy --conversation <id>` |
| `copilot` | Stores a stable session UUID and launches `copilot --session-id <uuid>` |
| `claude` | Stores a managed session UUID, starts with `claude --session-id <uuid>`, then resumes with `claude -r <uuid>` |
| `gemini` | Stores a managed session UUID, starts with `gemini --session-id <uuid>`, then resumes with `gemini --resume <uuid>` |
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
- One or more supported CLIs installed: Antigravity, Copilot, Claude Code, Gemini CLI, or Codex CLI

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
ai-session-manager setup agy copilot claude gemini codex
```

Each selected binary is renamed to `<tool>-real` and replaced with a thin Python wrapper. From that point on, keep using the original command name.

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

### Claude / Gemini

```bash
claude
# [ai-session-manager] New session 4f1a2b3c-... (my-project)

claude
# [ai-session-manager] Resuming session 4f1a2b3c-... (my-project)

gemini
# [ai-session-manager] New session 7b2f8c1d-... (my-project)

gemini
# [ai-session-manager] Resuming session 7b2f8c1d-... (my-project)
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
gemini --list-sessions
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
| `ai-session-manager setup [tools...]` | Install wrappers for all detected or selected tools |
| `ai-session-manager teardown [tools...]` | Remove wrappers and restore original binaries |
| `ai-session-manager status [tools...]` | Show platform, binary paths, and state files |
| `ai-session-manager reset [tools...]` | Delete persisted wrapper state for the current project |

---

## State layout

```text
project root:
  .ai-session-manager/
    copilot.json
    claude.json
    codex.json
    gemini.json
    agy.json
```

Copilot, Claude, and Gemini store an exact managed session identifier in their state files from the first launch.

AGY and Codex store the tool's own native conversation/session identifier once the wrapper can discover it from local history after a successful run. If no exact native ID is available yet, the wrapper falls back to the tool's native resume-latest/new-session behavior until it can record one.

### Platform details

| | Linux | macOS | Windows |
|---|---|---|---|
| Wrapper file | tool name (shebang script) | tool name (shebang script) | tool `.cmd` wrapper |
| Real binary | `<tool>-real` | `<tool>-real` | `<tool>-real.exe` or `<tool>-real.cmd` |
| Process launch | `os.execv` (true replace) | `os.execv` (true replace) | `subprocess` + exit code |

### Project structure

```text
ai-session-manager/
├── pyproject.toml
├── README.md
└── src/
    ├── ai_session_manager/
    │   ├── wrapper.py
    │   └── cli.py
```

---

## Reinstalling a tool CLI

If a wrapped tool is manually reinstalled and overwrites the wrapper, run setup again:

```bash
ai-session-manager setup copilot
```

---

## Uninstall

```bash
ai-session-manager teardown
pip uninstall ai-session-manager
```

## License

MIT
