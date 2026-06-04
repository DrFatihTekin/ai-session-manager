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
| `ai-session-manager session convert --from <tool> --to <target>` | Rebuild a supported source session as a resumable session for a proven target tool |

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

## Session migration

`ai-session-manager` currently supports these proven target combinations:

| From | To | Status |
|---|---|---|
| `copilot` | `claude` | Supported |
| `codex` | `claude` | Supported |
| `gemini` | `claude` | Supported |
| `agy` | `claude` | Supported |
| `claude` | `gemini` | Supported |
| `copilot` | `gemini` | Supported |
| `codex` | `gemini` | Supported |
| `gemini` | `gemini` | Supported |
| `agy` | `gemini` | Supported |

Example:

```bash
ai-session-manager session convert --from copilot --to claude
```

```bash
ai-session-manager session convert --from claude --to gemini --source-session <claude-session-id>
```

For `copilot`, the converter can read the current project's stored source session ID from `.ai-session-manager/copilot.json`.

For `claude`, `codex`, `gemini`, and `agy`, pass the source session explicitly:

```bash
ai-session-manager session convert --from claude --to gemini --source-session <claude-session-id>
ai-session-manager session convert --from codex --to claude --source-session <codex-session-id>
ai-session-manager session convert --from gemini --to claude --source-session <gemini-session-id>
ai-session-manager session convert --from agy --to claude --source-session <agy-brain-id-or-transcript-path>
```

The converter rebuilds the visible user/assistant chat history for the chosen proven target:

- `claude` target sessions are written to `~/.claude/projects/...` and future `claude` launches resume them with `claude -r <session-id>`.
- `gemini` target sessions are written to `.ai-session-manager/gemini-session-<id>.jsonl` in the project and future `gemini` launches resume them with `--session-file`.

Important limits:

- Only visible chat history is transferred today.
- Source-tool calls, tool outputs, attachments, checkpoints, and other hidden internal state are not portable to other targets.
- Unsupported tool pairs fail explicitly instead of silently degrading to a summary handoff.

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

---

## Publishing to PyPI

This repository includes a GitHub Actions workflow at `.github/workflows/publish-pypi.yml`.

What it does:

1. runs `pytest -q`
2. builds the package with `python -m build`
3. checks the artifacts with `python -m twine check dist/*`
4. publishes to PyPI

### Recommended setup: PyPI trusted publishing

Configure PyPI to trust this GitHub repository and workflow:

- PyPI project: `ai-session-manager`
- owner/repo: `DrFatihTekin/ai-session-manager`
- workflow file: `publish-pypi.yml`
- environment: `pypi`

The workflow uses GitHub OIDC via `pypa/gh-action-pypi-publish`, so no PyPI API token needs to be stored in GitHub secrets once trusted publishing is configured on the PyPI side.

### How to trigger a publish

Two triggers are enabled:

1. **Release publish**: publish a GitHub Release from a tag that points to a commit already contained in `main`
2. **Manual dispatch**: run the workflow from the Actions tab for a revision already contained in `main`

The workflow explicitly checks that the revision being published is contained in `origin/main`, so it will fail instead of publishing a feature branch by mistake.

Typical release flow:

```bash
git checkout main
git pull --ff-only origin main
git tag v0.1.0
git push origin main --tags
```

Then publish a GitHub Release for that tag.

---

## License

MIT
