# LLMCommit: automatic git commit messages (Ollama first, OpenAI second, Gemini final fallback)

`llmcommit` is a small wrapper around `git commit` that generates the commit message automatically from the changes
being committed.

It behaves like `git commit` (it forwards the usual `git commit` arguments) and adds extra options:

* `--lang <code>`: language for the generated message (default: `en`, e.g. `fi`)
* `--addall`: add all untracked files (not in .gitignore) before committing
* `--push`: push to remote after a successful commit

Example:

* `llmcommit -a --lang fi` commits all tracked changes and writes the commit message in Finnish.

## Requirements

* Git installed and available in PATH (`git --version`)
* Python 3.9+ installed and available in PATH (`python3 --version` or `python --version`)
* Primary option (recommended): Ollama installed and running locally
    * Default Ollama endpoint: `http://localhost:11434`
    * Default model: `qwen3:8b`
* Optional fallback 1: OpenAI API key (used only if OLLAMA_API_KEY is not set or Ollama fails)
* Optional fallback 2: Google Gemini API key (used only if neither Ollama nor OpenAI are available)

## Environment variables (optional)

| Variable            | Default                  | Description                           |
|---------------------|--------------------------|---------------------------------------|
| `OLLAMA_HOST`       | `http://localhost:11434` | Ollama server URL                     |
| `OLLAMA_MODEL`      | `qwen3:8b`               | Ollama model to use                   |
| `OPENAI_API_KEY`    | (none)                   | Required for OpenAI fallback          |
| `OPENAI_MODEL`      | `gpt-5-mini`             | OpenAI model to use                   |
| `OPENAI_BASE_URL`   | `https://api.openai.com` | OpenAI-compatible API base            |
| `GEMINI_API_KEY`    | (none)                   | Required for Gemini final fallback    |
| `GEMINI_MODEL`      | `gemini-pro`             | Gemini model to use                   |
| `LLMCOMMIT_DEBUG`   | (none)                   | Set to "1", "true", or "yes" for logs |

The tool attempts to generate commit messages in this order:
1. Ollama (local) - if `OLLAMA_HOST` is reachable
2. OpenAI (cloud) - if `OPENAI_API_KEY` is set and Ollama fails
3. Gemini (cloud) - if `GEMINI_API_KEY` is set and both Ollama and OpenAI fail

---

## Install as a global command

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

## Usage

From inside a Git repository (or any subdirectory inside it):

```bash
# Commit staged changes (generate message from staged diff)
llmcommit

# Commit all tracked changes (like git commit -a), message in Finnish
llmcommit -a --lang fi

# Add all untracked files and commit with generated message
llmcommit --addall

# Add all untracked files and commit all tracked changes with generated message
llmcommit -a --addall

# Amend last commit (message generated from the amended diff)
llmcommit --amend

# Dry run
llmcommit --dry-run

# Commit and push to remote
llmcommit --push

# Commit all tracked changes and push
llmcommit -a --push
```

**Notes:**

* If you pass `-m`, `-F`, `--template`, `--no-edit`, `--fixup`, `--squash`, `-C`, `-c`, or interactive flags like `-p`/
  `-i`, the tool will not auto-generate a message and will run `git commit` normally (to avoid surprising behavior).
* If you run it outside a repo, you'll get: `not inside a git repository`.
* Message generation follows a fallback chain: Ollama (local) → OpenAI (cloud) → Gemini (cloud, final fallback).

---

## Troubleshooting

**"LLMCommit: not inside a git repository."**

* `cd` into the repository you want to commit (or a subfolder of it), then retry.

**"No changes detected for commit message generation…"**

* If you want staged commits: `git add -A` then `llmcommit`
* If you want commit-all: use `llmcommit -a`
* If you want to add all untracked files and commit: use `llmcommit --addall`

**Ollama failures / slow responses**

* Ensure Ollama is running and the model exists locally.
* You can set:
    * `OLLAMA_HOST` (if not `http://localhost:11434`)
    * `OLLAMA_MODEL` (if not `qwen3:8b`)

**OpenAI fallback fails**

* Ensure `OPENAI_API_KEY` is set in your environment.
* This fallback is only used if Ollama is not available or fails.

**Gemini final fallback fails**

* Ensure `GEMINI_API_KEY` is set in your environment.
* This final fallback is only used if both Ollama and OpenAI are not available or fail.
* Note that `GEMINI_API_KEY` must be set for this service to be attempted.

**Debugging**

* Set `LLMCOMMIT_DEBUG=1` for verbose logs to stderr. Example:
    ```bash
    LLMCOMMIT_DEBUG=1 llmcommit -a
    ```

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
