# LLMCommit: Automatic Git Commit Messages

`llmcommit` is an intelligent wrapper around `git commit` that automatically generates commit messages from your changes
using AI. It supports multiple LLM providers with automatic fallback, local-first operation, and extensive customization
options.

## Features

✨ **Multi-Provider Support** - Ollama (local) → OpenAI → Gemini with automatic fallback  
🔒 **Privacy-First** - Tries local Ollama first, cloud APIs only as fallback  
🌍 **Multi-Language** - Generate messages in English, Finnish, Swedish, Estonian, German, French, or Spanish  
📝 **Conventional Commits** - Built-in support for conventional commit format  
⚙️ **Highly Configurable** - Config files, environment variables, and CLI flags  
🔄 **Interactive Review** - Edit AI-generated messages before committing  
🎯 **Smart Retry Logic** - Exponential backoff for transient failures  
⏱️ **Progress Indicators** - Beautiful spinner animations while waiting  
🛡️ **Secret Detection** - Automatic redaction of API keys and secrets from diffs

## Quick Start

```bash
# Commit staged changes with auto-generated message
llmcommit

# Commit all tracked changes with message in Finnish
llmcommit -a --lang fi

# Review and edit the generated message before committing
llmcommit --review -a

# Use Conventional Commits format
llmcommit --conventional

# Commit and push to remote
llmcommit -a --push
```

## Requirements

* Git installed and available in PATH (`git --version`)
* Python 3.9+ installed and available in PATH (`python3 --version` or `python --version`)
* **Primary option (recommended):** Ollama installed and running locally
    * Default Ollama endpoint: `http://localhost:11434`
    * Default model: `qwen3:8b`
* **Optional fallback 1:** OpenAI API key (used only if Ollama fails)
* **Optional fallback 2:** Google Gemini API key (used only if both Ollama and OpenAI fail)

## Command-Line Options

| Option                       | Description                                                   |
|------------------------------|---------------------------------------------------------------|
| `--lang <code>`              | Language for generated message (default: `en`)                |
| `--addall`                   | Add all untracked files (not in .gitignore) before committing |
| `--push`                     | Push to remote after successful commit                        |
| `--review` / `--interactive` | Open generated message in `$EDITOR` for review/editing        |
| `--conventional`             | Use Conventional Commits format                               |
| `--model <name>`             | Override model (auto-detects provider)                        |
| `--ollama-model <name>`      | Specific Ollama model override                                |
| `--openai-model <name>`      | Specific OpenAI model override                                |

All standard `git commit` flags are supported and passed through.

## Configuration

### Environment Variables

| Variable          | Default                  | Description                                 |
|-------------------|--------------------------|---------------------------------------------|
| `OLLAMA_HOST`     | `http://localhost:11434` | Ollama server URL                           |
| `OLLAMA_MODEL`    | `qwen3:8b`               | Ollama model to use                         |
| `OLLAMA_TIMEOUT`  | `30`                     | Ollama API timeout (seconds)                |
| `OPENAI_API_KEY`  | (none)                   | OpenAI API key for fallback                 |
| `OPENAI_MODEL`    | `gpt-4o-mini`            | OpenAI model to use                         |
| `OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI-compatible API base                  |
| `OPENAI_TIMEOUT`  | `25`                     | OpenAI API timeout (seconds)                |
| `GEMINI_API_KEY` | (none) | Google Gemini API key for final fallback |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model to use |
| `GEMINI_TIMEOUT` | `25` | Gemini API timeout (seconds) |
| `LLMCOMMIT_PROVIDERS` | `ollama,openai,gemini` | Provider order (comma-separated) |
| `LLMCOMMIT_DEBUG` | (none) | Set to "1", "true", or "yes" for debug logs |

### Configuration Files

Create `.llmcommit.json` in your home directory (`~/.llmcommit.json`) or project root:

**User-level config** (`~/.llmcommit.json`):

```json
{
  "ollama_host": "http://localhost:11434",
  "ollama_model": "qwen3:8b",
  "ollama_timeout": 30,
  "openai_model": "gpt-4o-mini",
  "openai_timeout": 25,
  "gemini_model": "gemini-1.5-flash",
  "gemini_timeout": 25
}
```

**Project-level config** (`.llmcommit.json` in git root):

```json
{
  "ollama_model": "llama3:70b",
  "openai_model": "gpt-4o"
}
```

**Configuration precedence** (highest to lowest):

1. Command-line flags (`--model`, `--ollama-model`, `--openai-model`)
2. Environment variables
3. Project-level config (`.llmcommit.json` in git root)
4. User-level config (`~/.llmcommit.json`)
5. Built-in defaults

### Provider Pipeline Configuration

You can configure which providers to use and in what order:

**Via config file** (`.llmcommit.json`):
```json
{
  "providers": "openai,ollama,gemini"
}
```

**Via environment variable:**
```bash
export LLMCOMMIT_PROVIDERS="openai,ollama,gemini"
```

**Common configurations:**
- `"ollama,openai,gemini"` - **Default**: try Ollama first, then OpenAI, then Gemini
- `"openai,gemini"` - Skip Ollama, use cloud providers only
- `"ollama"` - Local-only, no cloud fallback
- `"gemini,openai,ollama"` - Try Gemini first, then OpenAI, then Ollama

Providers without API keys are automatically skipped. Each provider includes **automatic retry with exponential backoff** for transient failures (network errors, rate limits).

---

## Installation

The goal is that you can type `llmcommit ...` from any directory.
Note: it will only succeed when your current directory is inside a Git repository (or a subfolder of one).

### macOS

1. Put the script somewhere stable, for example `~/bin/llmcommit` (recommended for a single-user install):

```bash
mkdir -p "$HOME/bin"
cp /path/to/LLMCommit.py "$HOME/bin/llmcommit"
chmod +x "$HOME/bin/llmcommit"
```

2. Ensure the first line of the script is a shebang:

```python
#!/usr/bin/env python3
```

3. Add `~/bin` to your PATH.

If you use zsh (default on modern macOS):

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

If you use bash:

```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bash_profile
source ~/.bash_profile
```

4. (Optional) Set OpenAI key for fallback:

```bash
export OPENAI_API_KEY="YOUR_KEY"
# persist (zsh):
echo 'export OPENAI_API_KEY="YOUR_KEY"' >> ~/.zshrc
source ~/.zshrc
```

### Linux

1. Install into `~/.local/bin` (common convention):

```bash
mkdir -p "$HOME/.local/bin"
cp /path/to/LLMCommit.py "$HOME/.local/bin/llmcommit"
chmod +x "$HOME/.local/bin/llmcommit"
```

2. Ensure `~/.local/bin` is on PATH (many distros already do this). If not:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

3. (Optional) Set OpenAI key for fallback:

```bash
export OPENAI_API_KEY="YOUR_KEY"
echo 'export OPENAI_API_KEY="YOUR_KEY"' >> ~/.bashrc
source ~/.bashrc
```

### Windows

You have two good options.

**Option A (simple): run via `python` / `py`**

1. Install Python 3 from python.org and ensure "Add Python to PATH" is enabled.

2. Put the script somewhere, for example `C:\Users\<you>\bin\llmcommit.py`

3. From inside a repo, run:

```powershell
py -3 C:\Users\<you>\bin\llmcommit.py -a --lang fi
```

**Option B (recommended): create a `llmcommit` command**

1. Create a folder for your tools: `C:\Users\<you>\bin`

2. Copy the Python script there as `C:\Users\<you>\bin\llmcommit.py`

3. Create a wrapper file next to it named `C:\Users\<you>\bin\llmcommit.cmd` with this content (edit the paths):

```bat
@echo off
py -3 "C:\Users\<you>\bin\llmcommit.py" %*
```

4. Add `C:\Users\<you>\bin` to your PATH:
    * Windows Settings → System → About → Advanced system settings
    * Environment Variables → select "Path" → Edit → New → add `C:\Users\<you>\bin`

5. Open a new terminal and verify:

```powershell
llmcommit -a --lang fi
```

6. (Optional) Set the OpenAI key:

```powershell
# Current session only:
$env:OPENAI_API_KEY="YOUR_KEY"

# Persist (adds to user environment variables):
setx OPENAI_API_KEY "YOUR_KEY"
```

---

## Usage Examples

### Basic Usage

```bash
# Commit staged changes with auto-generated message
llmcommit

# Commit all tracked changes (like git commit -a)
llmcommit -a

# Commit with message in Finnish
llmcommit -a --lang fi

# Add all untracked files and commit
llmcommit --addall

# Combine: add all untracked files + commit all tracked changes
llmcommit -a --addall
```

### Interactive Review

```bash
# Review and edit the generated message before committing
llmcommit --review -a

# Also works with --interactive
llmcommit --interactive
```

The generated message will open in your default editor (`$EDITOR` or `$VISUAL`). Edit as needed, save, and close to
proceed with the commit.

### Conventional Commits

```bash
# Generate message in Conventional Commits format
llmcommit --conventional

# Example output: "feat(auth): add OAuth2 support"
llmcommit --conventional -a

# Combined with review
llmcommit --conventional --review
```

Supported types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`

### Model Selection

```bash
# Use a specific OpenAI model
llmcommit --model gpt-4o

# Use a specific Ollama model
llmcommit --ollama-model llama3:70b

# Use OpenAI with explicit flag
llmcommit --openai-model gpt-4o-mini

# Try local llama first, fallback to OpenAI
llmcommit --ollama-model llama3:8b --openai-model gpt-4o
```

### Combined Workflows

```bash
# Review conventional commit, then push
llmcommit --conventional --review --push

# Amend last commit with new message
llmcommit --amend

# Dry run to see what would be committed
llmcommit --dry-run

# Commit all changes and push to remote
llmcommit -a --push

# Finnish conventional commit with review
llmcommit -a --lang fi --conventional --review

# Add untracked files, commit everything, use custom model, and push
llmcommit --addall -a --model gpt-4o --push
```

### Advanced Usage

```bash
# Use custom Ollama endpoint
OLLAMA_HOST=http://192.168.1.100:11434 llmcommit -a

# Use different OpenAI-compatible API
OPENAI_BASE_URL=https://my-proxy.com llmcommit -a

# Debug mode with detailed logs
LLMCOMMIT_DEBUG=1 llmcommit -a

# Custom timeout for slow connections
OLLAMA_TIMEOUT=60 llmcommit -a

# Disable Ollama, use OpenAI directly
OLLAMA_HOST=http://invalid llmcommit -a
```

### Supported Languages

| Code | Language          |
|------|-------------------|
| `en` | English (default) |
| `fi` | Finnish           |
| `sv` | Swedish           |
| `et` | Estonian          |
| `de` | German            |
| `fr` | French            |
| `es` | Spanish           |

Example: `llmcommit -a --lang sv` generates commit message in Swedish.

---

## Important Notes

* If you pass `-m`, `-F`, `--template`, `--no-edit`, `--fixup`, `--squash`, `-C`, `-c`, or interactive flags like `-p`/
  `-i`, the tool will not auto-generate a message and will run `git commit` normally (to avoid surprising behavior).
* If you run it outside a repo, you'll get: `not inside a git repository`.
* All standard `git commit` flags work as expected and are passed through to git.
* Progress spinners show while waiting for LLM responses (disabled in debug mode).
* Secret patterns (API keys, private keys, tokens) are automatically redacted from diffs before sending to LLMs.

## Troubleshooting

**"LLMCommit: not inside a git repository."**

* `cd` into the repository you want to commit (or a subfolder of it), then retry.

**"No changes detected for commit message generation…"**

* If you want staged commits: `git add -A` then `llmcommit`
* If you want commit-all: use `llmcommit -a`
* If you want to add all untracked files and commit: use `llmcommit --addall`

**Ollama failures / slow responses**

* Ensure Ollama is running: `ollama serve`
* Check if the model exists locally: `ollama list`
* Pull the model if needed: `ollama pull qwen3:8b`
* You can set:
    * `OLLAMA_HOST` (if not `http://localhost:11434`)
    * `OLLAMA_MODEL` (if not `qwen3:8b`)
    * `OLLAMA_TIMEOUT` (if you need more time)

**OpenAI fallback fails**

* Ensure `OPENAI_API_KEY` is set in your environment.
* Check your API key at https://platform.openai.com/api-keys
* Verify the model exists: `gpt-4o-mini`, `gpt-4o`, `gpt-3.5-turbo` are valid
* This fallback is only used if Ollama is not available or fails.

**Gemini final fallback fails**

* Ensure `GEMINI_API_KEY` is set in your environment.
* Get your API key at https://aistudio.google.com/app/apikey
* Verify the model name: `gemini-1.5-flash`, `gemini-1.5-pro` are valid
* This final fallback is only used if both Ollama and OpenAI fail.
* Note that `GEMINI_API_KEY` must be set for this service to be attempted.

**Rate limiting errors**

* The tool automatically retries with exponential backoff for rate limits.
* If you still hit limits, wait a few minutes or upgrade your API tier.
* Use `--ollama-model` to force local processing and avoid API limits.

**Debugging**

* Set `LLMCOMMIT_DEBUG=1` for verbose logs to stderr. Example:
    ```bash
    LLMCOMMIT_DEBUG=1 llmcommit -a
    ```
* This shows the full request/response cycle, model selection, and error details.

**SSL Certificate Error: "certificate verify failed: unable to get local issuer certificate"**

This error occurs when Python cannot verify SSL certificates for HTTPS connections. It is **most common on macOS** but
can also occur on Linux (especially in Docker containers or minimal installations) and occasionally on Windows in
corporate environments.

*macOS fix (most common):*

Python installations from python.org on macOS don't use the system certificate store by default. Run the certificate
installer that came with your Python installation:

```bash
# For Python installed from python.org (adjust version number as needed)
/Applications/Python\ 3.12/Install\ Certificates.command
```

Or if you use Homebrew/pyenv Python:

```bash
pip3 install --upgrade certifi
```

*Linux fix:*

Install the CA certificates package:

```bash
# Debian/Ubuntu
sudo apt-get install ca-certificates

# Fedora/RHEL
sudo dnf install ca-certificates

# Alpine (common in Docker)
apk add ca-certificates
```

*Windows fix:*

This is rare on Windows since Python uses the Windows certificate store. If it occurs in a corporate environment,
contact your IT department about installing the corporate root certificates.

*Temporary workaround (not recommended for production):*

If you need a quick fix and trust your network, you can disable SSL verification:

```bash
export PYTHONHTTPSVERIFY=0
llmcommit -a
```

**Warning:** This disables SSL verification for all Python HTTPS requests in that session, which is a security risk on
untrusted networks.

---

## Security

* **Secret Detection**: The tool automatically redacts common secret patterns before sending diffs to LLMs:
    * Private SSH/RSA/EC keys
    * AWS access keys (AKIA*, ASIA*)
    * OpenAI API keys (sk-*)
    * GitHub tokens (ghp_*, github_pat_*)
    * Google API keys (AIza*)
    * Generic patterns (api_key, secret, token, password in quotes)

* **Local-First**: By default, the tool tries Ollama (local) first, only falling back to cloud APIs if Ollama fails.

* **No Data Storage**: The tool does not store your code or commit messages anywhere. Each request is independent.

* **API Key Security**: Gemini API keys are passed in headers (not URL parameters) to prevent exposure in logs.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. When contributing:

1. Ensure the script remains a single file with zero dependencies
2. Test with all three providers (Ollama, OpenAI, Gemini)
3. Test edge cases (no changes, large diffs, errors)
4. Update README.md if adding features
5. Follow the existing code style (PEP 8, type hints)

---

## License

This project is open source. Feel free to use, modify, and distribute as needed.

---

## Changelog

### Latest (Current)

- ✨ Added interactive review mode (`--review`, `--interactive`)
- ✨ Added Conventional Commits support (`--conventional`)
- ✨ Added configuration file support (`.llmcommit.json`)
- ✨ Added CLI model selection (`--model`, `--ollama-model`, `--openai-model`)
- ✨ Added configurable timeouts via environment variables
- ✨ Added progress indicators (spinner animations)
- ✨ Added retry logic with exponential backoff
- ✨ Fixed OpenAI API integration (correct endpoint and payload format)
- ✨ Fixed Gemini API key exposure (now uses headers)
- ✨ Updated default models (`gpt-4o-mini`, `gemini-1.5-flash`)
- ✨ Improved `--addall` error handling with user confirmation
- ✨ Enhanced error messages for common issues
- 🔒 Improved secret detection and sanitization

### Earlier Versions

- Initial release with Ollama, OpenAI, and Gemini support
- Multi-language commit messages
- `--addall` and `--push` flags
- Basic secret pattern redaction
