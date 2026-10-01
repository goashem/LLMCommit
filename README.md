# LLMCommit

A `git commit` wrapper that writes commit messages for you. Tries your local Ollama first, then falls back to OpenAI,
Claude and Gemini, in that order.

## What it does

You run `llmcommit` instead of `git commit`. It looks at your staged changes, sends them to an LLM, and uses the
response as your commit message.

```bash
# Commit staged changes
llmcommit

# Commit everything (-a) in Finnish
llmcommit -a --lang fi

# Review the message before committing
llmcommit --review -a

# Conventional commits format (feat:, fix:, etc.)
llmcommit --conventional

# Commit and push
llmcommit -a --push

```

## Requirements

- Git
- Python 3.9+
- At least one of:
    - Ollama running locally (default: `http://localhost:11434`, model: `qwen3:8b`)
    - OpenAI API key (`OPENAI_API_KEY`)
    - Claude Code login token (`CLAUDE_CODE_OAUTH_TOKEN`) or Anthropic API key (`ANTHROPIC_API_KEY`)
    - Gemini API key (`GEMINI_API_KEY`)

## Options

| Option                  | What it does                                 |
|-------------------------|----------------------------------------------|
| `--lang <code>`         | Message language: en, fi, sv, et, de, fr, es |
| `--addall`              | Stage all untracked files first              |
| `--push`                | Push after committing                        |
| `--review`              | Open message in $EDITOR before committing    |
| `--conventional`        | Use conventional commits format              |
| `--model <name>`        | Override model (auto-detects provider)       |
| `--ollama-model <name>` | Force a specific Ollama model                |
| `--openai-model <name>` | Force a specific OpenAI model                |
| `--claude-model <name>` | Force a specific Claude model                |
| `--dry-run`             | Show what would happen, don't commit         |
| `--amend`               | Amend the previous commit                    |

Standard `git commit` flags pass through.

## Configuration

### Environment variables

| Variable                  | Default                       | Notes                                    |
|---------------------------|-------------------------------|------------------------------------------|
| `OLLAMA_HOST`             | `http://localhost:11434`      |                                          |
| `OLLAMA_MODEL`            | `qwen3:8b`                    |                                          |
| `OLLAMA_TIMEOUT`          | `30`                          | seconds                                  |
| `OPENAI_API_KEY`          | -                             | required for OpenAI fallback             |
| `OPENAI_MODEL`            | `gpt-6-luna`                  | sent with reasoning off where supported  |
| `OPENAI_BASE_URL`         | `https://api.openai.com`      | for OpenAI-compatible APIs               |
| `OPENAI_TIMEOUT`          | `25`                          | seconds                                  |
| `CLAUDE_CODE_OAUTH_TOKEN` | -                             | Claude fallback; used if both are set    |
| `ANTHROPIC_API_KEY`       | -                             | Claude fallback, standard API key        |
| `CLAUDE_MODEL`            | `claude-sonnet-4-6`           |                                          |
| `CLAUDE_TIMEOUT`          | `30`                          | seconds                                  |
| `GEMINI_API_KEY`          | -                             | required for Gemini fallback             |
| `GEMINI_MODEL`            | `gemini-3.6-flash`            |                                          |
| `GEMINI_TIMEOUT`          | `25`                          | seconds                                  |
| `LLMCOMMIT_PROVIDERS`     | `ollama,openai,claude,gemini` | order to try providers                   |
| `LLMCOMMIT_DEBUG`         | -                             | set to 1 for verbose logs                |

### Config files

Put a `.llmcommit.json` in your home directory or project root:

```json
{
  "ollama_host": "http://localhost:11434",
  "ollama_model": "qwen3:8b",
  "ollama_timeout": 30,
  "openai_model": "gpt-6-luna",
  "gemini_model": "gemini-3.6-flash"
}
```

Precedence: CLI flags > env vars > project config > user config > defaults.

### Provider order

Change which providers are tried and in what order:

```bash
# Skip Ollama, cloud only
export LLMCOMMIT_PROVIDERS="openai,claude,gemini"

# Local only, no cloud
export LLMCOMMIT_PROVIDERS="ollama"
```

Providers without API keys are skipped automatically.

## Installation

### macOS / Linux

```bash
# Put it somewhere on your PATH
mkdir -p "$HOME/bin"
cp LLMCommit.py "$HOME/bin/llmcommit"
chmod +x "$HOME/bin/llmcommit"

# Add to PATH (zsh)
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Or for bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Linux convention is `~/.local/bin` instead of `~/bin`.

### Windows

Either run it directly:

```powershell
py -3 C:\path\to\llmcommit.py -a
```

Or create a wrapper. Put `llmcommit.py` and `llmcommit.cmd` in a folder on your PATH:

```bat
@echo off
py -3 "%~dp0llmcommit.py" %*
```

## Examples

```bash
# Basic
llmcommit           # commit staged changes
llmcommit -a        # commit all tracked changes

# Different language
llmcommit --lang fi # Finnish
llmcommit --lang sv # Swedish

# Review before committing
llmcommit --review -a

# Conventional commits
llmcommit --conventional
# outputs something like: feat(auth): add OAuth2 support

# Combined
llmcommit -a --conventional --review --push

# Custom model
llmcommit --model gpt-4o
llmcommit --ollama-model llama3:70b

# Debug
LLMCOMMIT_DEBUG=1 llmcommit -a
```

## When it won't generate a message

If you pass `-m`, `-F`, `--template`, `--no-edit`, `--fixup`, `--squash`, `-C`, `-c`, `-p`, or `-i`, the tool runs
`git commit` normally without generating anything. It assumes you know what you're doing.

## Troubleshooting

**"not inside a git repository"**

- cd into your repo first

**"No changes detected"**

- Stage something: `git add -A` then `llmcommit`
- Or use `llmcommit -a` to commit tracked changes

**Ollama not working**

- Check it's running: `ollama serve`
- Check the model exists: `ollama list`
- Pull if needed: `ollama pull qwen3:8b`

**OpenAI failing**

- Check `OPENAI_API_KEY` is set
- Verify it at https://platform.openai.com/api-keys

**Claude failing**

- Check `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` is set; the OAuth token wins if both are
- Get an API key at https://console.anthropic.com/

**Gemini failing**

- Check `GEMINI_API_KEY` is set
- Get one at https://aistudio.google.com/app/apikey

**SSL certificate errors (common on macOS)**

Python from python.org doesn't use the system certificate store. Run:

```bash
/Applications/Python\ 3.12/Install\ Certificates.command
```

Or with Homebrew/pyenv:

```bash
pip3 install --upgrade certifi
```

On Linux, install `ca-certificates`. On Windows this is rare; talk to IT if you're behind a corporate proxy.

## Security

The tool redacts common secret patterns before sending the diff, the file list and `git status` to LLMs:

- Private keys (PEM blocks: RSA, EC, DSA, OpenSSH, PKCS#8, PGP) and lines that are nothing but base64
- AWS access keys
- OpenAI keys (sk-*, sk-proj-*, sk-svcacct-*, sk-admin-*) and Anthropic keys (sk-ant-*)
- GitHub tokens (ghp_*, gho_*, ghu_*, ghs_*, ghr_*, github_pat_*)
- Google API keys (AIza*)
- Assignments whose name ends in a secret word, quoted or not: `OPENAI_API_KEY=…`, `"client_secret": "…"`,
  `password: …`, `**Salasana:** …`

Redaction is best-effort pattern matching, not a guarantee.

By default it tries Ollama first, so your code stays local unless Ollama fails. If `LLMCOMMIT_PROVIDERS` or the
`providers` config key puts a cloud provider first, the diff goes to that provider instead. Nothing is stored. Each
request is independent.

## Contributing

Keep it a single file with zero dependencies. Test all three providers. Update the README if you add features.

## Licence

Open source. Use it however you want.

## Changelog

### Latest

- Interactive review mode (`--review`)
- Conventional commits (`--conventional`)
- Config file support (`.llmcommit.json`)
- CLI model selection (`--model`, `--ollama-model`, `--openai-model`)
- Configurable timeouts
- Spinner while waiting
- Retry with exponential backoff
- Fixed OpenAI API integration
- Fixed Gemini API key exposure (now in headers, not URL)
- Updated default models (`gpt-4o-mini`, `gemini-1.5-flash`)

### Earlier

- Initial release with Ollama, OpenAI, Gemini
- Multi-language messages
- `--addall` and `--push`
- Secret redaction
