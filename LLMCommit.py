#!/usr/bin/env python3
# LLMCommit
#
# Usage examples:
#   LLMCommit -a --lang fi
#   LLMCommit --amend
#   LLMCommit --dry-run
#   LLMCommit --addall
#   LLMCommit -a --addall
#   LLMCommit --push
#   LLMCommit -a --push
#
# Env vars:
#   OLLAMA_HOST=http://localhost:11434
#   OLLAMA_MODEL=qwen3:8b
#   OPENAI_API_KEY=...
#   OPENAI_MODEL=gpt-5-mini
#   OPENAI_BASE_URL=https://api.openai.com

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from typing import List, Tuple

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com").rstrip("/")

DEBUG = os.environ.get("LLMCOMMIT_DEBUG", "").strip().lower() in ("1", "true", "yes")


def debug_log(msg: str) -> None:
    """Print debug message to stderr if DEBUG is enabled."""
    if DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


# Best-effort: avoid sending obvious secrets in diffs.
SECRET_PATTERNS = [re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?-----END .*?PRIVATE KEY-----", re.DOTALL),
                   re.compile(r"\bAKIA[0-9A-Z]{16}\b"), re.compile(r"\bASIA[0-9A-Z]{16}\b"), re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
                   re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), re.compile(r"\bAIza[0-9A-Za-z\-_]{30,}\b"),
                   re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"][^'\"\n]{6,}['\"]"), ]

LANG_NAMES = {"en": "English", "fi": "Finnish", "sv": "Swedish", "et": "Estonian", "de": "German", "fr": "French", "es": "Spanish", }

# If these are present, git commit itself is deciding/using a message; we should not override.
MESSAGE_CONTROL_FLAGS = {"--no-edit", "--reuse-message", "-C", "--reedit-message", "-c", "--fixup", "--squash", }

# If interactive staging is requested, the final diff is not known upfront.
INTERACTIVE_FLAGS = {"-p", "--patch", "-i", "--interactive"}


def sanitize_text(s: str) -> str:
    """
    Sanitizes the input text by replacing occurrences of secret patterns
    with the string "[REDACTED]".

    This function iterates through a list of pre-defined secret patterns
    and substitutes any matched segments in the given text with a redacted
    indicator, thereby eliminating sensitive information from the input
    text.

    Args:
        s: The input string that may contain sensitive information.

    Returns:
        A new string where all occurrences of secret patterns are
        replaced with "[REDACTED]".
    """
    out = s
    for pat in SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def run_git(args: List[str]) -> str:
    """
    Runs a Git command with the specified arguments and returns the output.

    This function executes a Git command by combining "git" with the
    provided list of arguments. It captures the standard output and
    standard error of the command execution. If the Git command fails,
    it raises a RuntimeError with the error message from the command.

    Parameters:
        args: List of strings representing the arguments to pass to
        the Git command.

    Returns:
        The standard output of the Git command as a string.

    Raises:
        RuntimeError: If the Git command fails to execute successfully,
        an error message is provided from the standard error of the
        command.
    """
    p = subprocess.run(["git", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "git command failed")
    return p.stdout


def inside_git_repo() -> bool:
    """
    Determines if the current directory is inside a Git repository.

    This function executes a Git command to check if the current directory
    is within a Git working tree. It attempts to run the 'rev-parse
    --is-inside-work-tree' command using a helper function 'run_git'.
    If the command executes successfully, it returns True, indicating
    that the directory is inside a Git repository. If an exception is
    caught, it returns False, indicating that the directory is not part
    of a Git repository.

    Returns:
        bool: True if the current directory is inside a Git repository,
        otherwise False.
    """
    try:
        run_git(["rev-parse", "--is-inside-work-tree"])
        return True
    except Exception:
        return False


def split_lang_arg(argv: List[str]) -> Tuple[str, List[str], bool, bool]:
    """
    Splits language argument from a list of arguments and detects --addall and --push flags.

    This function processes command-line arguments to separate out a language
    specification if present. By default, it assumes the language is 'en'
    (English) unless the "--lang" option is provided followed by another
    language code. It also detects the --addall and --push flags.

    Args:
        argv: A list of strings representing command-line arguments.

    Returns:
        A tuple containing the language code specified or the default 'en',
        a list of the remaining arguments, a boolean indicating if --addall was specified,
        and a boolean indicating if --push was specified.

    Raises:
        SystemExit: If the "--lang" option is provided without an accompanying
        value.
    """
    lang = "en"
    addall = False
    push = False
    out: List[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--lang":
            if i + 1 >= len(argv):
                raise SystemExit("LLMCommit: --lang requires a value (e.g. --lang fi)")
            lang = argv[i + 1]
            i += 2
            continue
        elif argv[i] == "--addall":
            addall = True
            i += 1
            continue
        elif argv[i] == "--push":
            push = True
            i += 1
            continue
        out.append(argv[i])
        i += 1
    return lang, out, addall, push


def detect_pathspec(args: List[str]) -> List[str]:
    """
    Best-effort parsing of pathspec(s):
    - If '--' is present, everything after it is treated as pathspec.
    - Otherwise, pathspec handling is complex; we conservatively only use the '--' form.
    """
    if "--" in args:
        idx = args.index("--")
        return args[idx + 1:]
    return []


def should_not_autogenerate(args: List[str]) -> bool:
    """
    Determines if autogeneration should be bypassed based on the presence of
    specific flags or options in the arguments. It checks for interactive
    flags, message control flags, and certain message-providing options
    that would override default behavior.

    Parameters:
    args: List[str]
        A list of argument strings to evaluate.

    Returns:
    bool
        True if autogeneration should not occur, False otherwise.
    """
    # If user explicitly requested message behavior or interactive staging, do not autogenerate.
    if any(a in INTERACTIVE_FLAGS for a in args):
        return True

    # Message-providing options where overriding would be surprising.
    if any(a in MESSAGE_CONTROL_FLAGS for a in args):
        return True

    # -m/--message or -F/--file or --template/-t
    for i, a in enumerate(args):
        if a in ("-m", "--message", "-F", "--file", "-t", "--template"):
            return True
        # combined short form: -m"msg" is possible
        if a.startswith("-m") and len(a) > 2:
            return True
        if a.startswith("-F") and len(a) > 2:
            return True
        if a.startswith("-t") and len(a) > 2:
            return True

    return False


def build_git_context(args: List[str], max_chars: int = 14000) -> str:
    """
    Determine what diff to summarize:
    - If -a/--all/--include is present, include working tree tracked changes vs HEAD.
    - Else summarize staged index (--cached).
    Apply pathspec only if provided via '-- <paths...>'.
    """
    include_worktree = any(a in args for a in ("-a", "--all", "--include"))
    pathspec = detect_pathspec(args)
    debug_log(f"build_git_context: include_worktree={include_worktree}, pathspec={pathspec}")

    if include_worktree:
        ns_cmd = ["diff", "--name-status", "HEAD"]
        diff_cmd = ["diff", "--no-color", "HEAD"]
    else:
        ns_cmd = ["diff", "--cached", "--name-status"]
        diff_cmd = ["diff", "--cached", "--no-color"]

    if pathspec:
        ns_cmd += ["--", *pathspec]
        diff_cmd += ["--", *pathspec]

    debug_log(f"build_git_context: ns_cmd={ns_cmd}, diff_cmd={diff_cmd}")
    name_status = run_git(ns_cmd).strip()
    diff = run_git(diff_cmd)
    diff = sanitize_text(diff)
    debug_log(f"build_git_context: diff length={len(diff)}, name_status lines={len(name_status.splitlines())}")

    # Helpful extra context
    status = run_git(["status", "--porcelain=v1"]).strip()

    if not diff.strip():
        # Common case: user didn't stage anything and didn't request -a/--all
        raise RuntimeError("No changes detected for commit message generation.\n"
                           "If you meant to commit all tracked changes, use -a. Otherwise stage changes first (git add -A).")

    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n\n[DIFF TRUNCATED]\n"

    return ("Staged/selected file summary (name-status):\n"
            f"{name_status or '(none)'}\n\n"
            "Repo status (porcelain):\n"
            f"{status or '(clean or not available)'}\n\n"
            "Diff of what will be committed:\n"
            f"{diff.strip()}\n")


def system_instructions(lang_code: str) -> str:
    """
    Generates guidelines for creating git commit messages in a specified language.

    This function provides instructions for writing effective git commit messages
    in the language specified by the language code. It retrieves the full language
    name based on the provided code and constructs a set of rules that dictate
    the format and content of the commit message, emphasizing conciseness and
    clarity on the changes made and their purposes.

    Parameters:
        lang_code: str
            The code representing the language in which the commit message
            should be written.

    Returns:
        str
            A string containing instructions tailored for writing a git
            commit message in the specified language, including formatting
            and content guidelines.
    """
    lang_name = LANG_NAMES.get(lang_code.lower())
    lang_line = f"Write the commit message in {lang_name}." if lang_name else f"Write the commit message in language code '{lang_code}'."

    return ("You write excellent git commit messages.\n\n"
            f"{lang_line}\n"
            "Rules:\n"
            "- Output ONLY the commit message text (no quotes, no code fences, no commentary).\n"
            "- First line: concise summary <= 72 characters.\n"
            "- If useful, add a blank line then a short body (bullets allowed).\n"
            "- Describe WHAT changed and WHY.\n"
            "- Do not mention AI, LLMs, prompts, or tooling.\n")


def call_ollama(system: str, user: str, timeout_s: int = 25) -> str:
    """
    Makes a call to the Ollama API chat endpoint to interact with a model using
    specified system and user messages. Returns the response from the model
    as a string. The function constructs a JSON payload and sends an HTTP POST
    request with the specified system and user messages. It waits for a response
    within a specified timeout period. The response message content, if available,
    is stripped of leading and trailing whitespace before being returned.

    Parameters:
    system: The system message to include in the payload.
    user: The user message to include in the payload.
    timeout_s: The timeout in seconds for the API call. Defaults to 25.

    Returns:
    The content of the response message from the API, as a stripped string.
    """
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {"model": OLLAMA_MODEL, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "options": {"temperature": 0.2}, }
    debug_log(f"Ollama request URL: {url}")
    debug_log(f"Ollama model: {OLLAMA_MODEL}")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        debug_log(f"Ollama raw response: {raw[:1000]}{'...' if len(raw) > 1000 else ''}")
        j = json.loads(raw)
        text = (j.get("message") or {}).get("content") or ""
        debug_log(f"Ollama extracted text: {text[:500]}{'...' if len(text) > 500 else ''}")
        return text.strip()


def extract_openai_text(j: dict) -> str:
    """
    Extracts and returns textual content from a given dictionary. The function
    prioritizes the "output_text" key if it exists and is a non-empty string. If
    not, it will parse the "output" key if it is a list, looking for items
    where the type is "message" and the role is "assistant". It then compiles
    text content from these items if they are of type "output_text" or "text".

    Args:
        j: Dictionary containing potential text elements to extract.

    Returns:
        A string containing the extracted text content. If no appropriate content
        is found, an empty string is returned.
    """
    if isinstance(j.get("output_text"), str) and j["output_text"].strip():
        return j["output_text"].strip()

    parts: List[str] = []
    output = j.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") in ("output_text", "text") and isinstance(c.get("text"), str):
                    parts.append(c["text"])
    return "\n".join(p.strip() for p in parts if p.strip()).strip()


def call_openai(system: str, user: str, timeout_s: int = 25) -> str:
    """
    Call the OpenAI API to generate a response based on provided system instructions
    and user input. The function constructs a request with a specified timeout, sends
    it to the OpenAI service, and returns the text output from the response. If the API
    key is not set or if the response does not include text output, a RuntimeError is raised.

    Parameters:
        system (str): The instructions for the OpenAI model to follow.
        user (str): The user input to be processed by the OpenAI model.
        timeout_s (int): The timeout for the API request in seconds. Defaults to 25.

    Returns:
        str: The text output from the OpenAI response.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    url = f"{OPENAI_BASE_URL}/v1/responses"
    # Reasoning models (o1, o3, gpt-5, etc.) need more tokens for internal reasoning
    is_reasoning_model = bool(re.match(r"^(o[0-9]|gpt-5)", OPENAI_MODEL))
    max_tokens = 2000 if is_reasoning_model else 220
    debug_log(f"Model {OPENAI_MODEL} is_reasoning_model={is_reasoning_model}, max_output_tokens={max_tokens}")
    payload = {"model": OPENAI_MODEL, "instructions": system, "input": user, "max_output_tokens": max_tokens, "store": False, }
    # Reasoning models don't support temperature
    use_temperature = not is_reasoning_model
    if use_temperature:
        payload["temperature"] = 0.2
    debug_log(f"OpenAI request URL: {url}")
    debug_log(f"OpenAI model: {OPENAI_MODEL}")
    debug_log(f"OpenAI payload (without input): { {k: v for k, v in payload.items() if k != 'input'} }")
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            debug_log(f"OpenAI raw response: {raw[:2000]}{'...' if len(raw) > 2000 else ''}")
            j = json.loads(raw)
            text = extract_openai_text(j)
            debug_log(f"OpenAI extracted text: {text[:500] if text else '(empty)'}")
            if not text:
                raise RuntimeError("OpenAI response contained no text output")
            return text.strip()
    except urllib.error.HTTPError as e:
        # Check if error is due to unsupported temperature parameter
        if e.code == 400 and use_temperature:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            debug_log(f"OpenAI HTTP 400 body: {body}")
            if "temperature" in body.lower():
                print(f"LLMCommit: Model {OPENAI_MODEL} does not support temperature, retrying without it.", file=sys.stderr)
                payload.pop("temperature", None)
                debug_log(f"OpenAI retry payload (without input): { {k: v for k, v in payload.items() if k != 'input'} }")
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data, method="POST", headers=headers)
                with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                    debug_log(f"OpenAI retry raw response: {raw[:2000]}{'...' if len(raw) > 2000 else ''}")
                    j = json.loads(raw)
                    text = extract_openai_text(j)
                    debug_log(f"OpenAI retry extracted text: {text[:500] if text else '(empty)'}")
                    if not text:
                        raise RuntimeError("OpenAI response contained no text output")
                    return text.strip()
        raise


def normalize_message(msg: str) -> str:
    """

    """
    s = msg.strip()
    s = re.sub(r"^\s*```.*?\n", "", s)
    s = re.sub(r"\n\s*```\s*$", "", s)
    s = s.strip().strip('"').strip("'").strip()

    lines = s.splitlines()
    if not lines:
        return ""

    subject = lines[0].strip()
    if len(subject) > 72:
        cut = subject[:72]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        subject = cut.rstrip(" ,;:-")

    body = "\n".join(lines[1:]).rstrip()
    return subject + ("\n" + body if body else "")


def message_to_git_m_args(msg: str) -> List[str]:
    """
    Converts a commit message into a list of Git command-line arguments.

    This function takes a commit message string, splits it into subject and
    body, and formats it into a list that can be used as command-line
    arguments for Git commit commands. The subject is the first line of
    the message, and the body comprises the rest of the lines.

    Parameters:
        msg: The commit message to convert. It should be in standard Git
        message format, where the first line is the subject and subsequent
        lines form the body.

    Returns:
        A list of strings suitable for use as arguments in a Git commit
        command, with each line converted into a separate command-line
        argument preceded by '-m'.
    """
    lines = msg.splitlines()
    subject = lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    args = ["-m", subject]
    if body:
        args += ["-m", body]
    return args


def main() -> int:
    """
    Main entry point for the application to automatically generate a git commit message.

    This function checks if the user is inside a Git repository and processes the
    command-line arguments to determine the mode of operation. If automatic
    commit message generation is deemed appropriate, it attempts to generate a
    commit message using either the Ollama service first, or falls back to
    using OpenAI if needed.

    Return:
        int: The exit code indicating the result of the operation; returns 2 if not
        inside a Git repository or if context building fails, 3 if message
        generation fails, otherwise returns the subprocess return code from
        Git commands.
    """
    debug_log(f"LLMCommit starting, args: {sys.argv[1:]}")
    if not inside_git_repo():
        print("LLMCommit: not inside a git repository.", file=sys.stderr)
        return 2

    lang, git_args, addall, push = split_lang_arg(sys.argv[1:])
    debug_log(f"Language: {lang}, git_args: {git_args}, addall: {addall}, push: {push}")

    # If --addall is specified, add all untracked files that are not in .gitignore
    if addall:
        try:
            # Get list of untracked files that are not ignored
            untracked_files = run_git(["ls-files", "--others", "--exclude-standard"]).strip()
            if untracked_files:
                file_list = untracked_files.split('\n')
                debug_log(f"Adding untracked files: {file_list}")
                # Add each file individually to handle potential errors gracefully
                for file in file_list:
                    if file:  # Skip empty strings
                        run_git(["add", file])
        except Exception as e:
            print(f"LLMCommit: Warning - failed to add untracked files: {e}", file=sys.stderr)

    # If user chose interactive commit or explicit message behavior, do not override.
    if should_not_autogenerate(git_args):
        debug_log("Skipping autogeneration, passing through to git")
        p = subprocess.run(["git", "commit", *git_args])
        if push and p.returncode == 0:
            debug_log("Pushing to remote...")
            push_result = subprocess.run(["git", "push"])
            return push_result.returncode
        return p.returncode

    # Build prompt from what will be committed.
    try:
        ctx = build_git_context(git_args)
        debug_log(f"Context built, length: {len(ctx)}")
    except Exception as e:
        print(f"LLMCommit: {e}", file=sys.stderr)
        return 2

    system = system_instructions(lang)
    user = "Generate a high-quality git commit message for these changes.\n\n" + ctx

    msg = ""
    # 1) Ollama first
    debug_log("Trying Ollama...")
    try:
        msg = call_ollama(system, user)
        debug_log(f"Ollama returned message length: {len(msg)}")
    except Exception as e:
        debug_log(f"Ollama failed: {e}")
        msg = ""

    # 2) OpenAI fallback
    if not msg.strip():
        debug_log("Trying OpenAI fallback...")
        try:
            msg = call_openai(system, user)
            debug_log(f"OpenAI returned message length: {len(msg)}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            debug_log(f"OpenAI HTTP error {e.code}: {body}")
            print(f"LLMCommit: OpenAI HTTP {e.code}: {body or e.reason}", file=sys.stderr)
            return 3
        except Exception as e:
            debug_log(f"OpenAI failed: {e}")
            print(f"LLMCommit: OpenAI call failed: {e}", file=sys.stderr)
            return 3

    debug_log(f"Raw message before normalization: {msg[:500] if msg else '(empty)'}")
    msg = normalize_message(msg)
    debug_log(f"Normalized message: {msg[:500] if msg else '(empty)'}")
    if not msg:
        print("LLMCommit: failed to generate a commit message.", file=sys.stderr)
        return 3

    # Inject the message into git commit args.
    final_args = [*git_args, *message_to_git_m_args(msg)]
    debug_log(f"Final git commit args: {final_args}")
    p = subprocess.run(["git", "commit", *final_args])

    # Push if --push was specified and commit succeeded
    if push and p.returncode == 0:
        debug_log("Pushing to remote...")
        push_result = subprocess.run(["git", "push"])
        return push_result.returncode

    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
