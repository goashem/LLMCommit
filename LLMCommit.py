#!/usr/bin/env python3
# LLMCommit
#
# Usage examples:
#   LLMCommit -a --lang fi
#   LLMCommit --amend
#   LLMCommit --dry-run
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
    out = s
    for pat in SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def run_git(args: List[str]) -> str:
    p = subprocess.run(["git", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or "git command failed")
    return p.stdout


def inside_git_repo() -> bool:
    try:
        run_git(["rev-parse", "--is-inside-work-tree"])
        return True
    except Exception:
        return False


def split_lang_arg(argv: List[str]) -> Tuple[str, List[str]]:
    """
    Extracts --lang <code> from argv and returns (lang, remaining_args).
    If multiple --lang occurrences exist, last one wins.
    """
    lang = "en"
    out: List[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--lang":
            if i + 1 >= len(argv):
                raise SystemExit("LLMCommit: --lang requires a value (e.g. --lang fi)")
            lang = argv[i + 1]
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return lang, out


def has_flag(args: List[str], flag: str) -> bool:
    return flag in args


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

    if include_worktree:
        ns_cmd = ["diff", "--name-status", "HEAD"]
        diff_cmd = ["diff", "--no-color", "HEAD"]
    else:
        ns_cmd = ["diff", "--cached", "--name-status"]
        diff_cmd = ["diff", "--cached", "--no-color"]

    if pathspec:
        ns_cmd += ["--", *pathspec]
        diff_cmd += ["--", *pathspec]

    name_status = run_git(ns_cmd).strip()
    diff = run_git(diff_cmd)
    diff = sanitize_text(diff)

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
    url = f"{OLLAMA_HOST}/api/chat"
    payload = {"model": OLLAMA_MODEL, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "options": {"temperature": 0.2}, }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        j = json.loads(resp.read().decode("utf-8", errors="replace"))
        text = (j.get("message") or {}).get("content") or ""
        return text.strip()


def extract_openai_text(j: dict) -> str:
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
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")

    url = f"{OPENAI_BASE_URL}/v1/responses"
    payload = {"model": OPENAI_MODEL, "instructions": system, "input": user, "temperature": 0.2, "max_output_tokens": 220, "store": False, }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"}
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)

    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        j = json.loads(resp.read().decode("utf-8", errors="replace"))
        text = extract_openai_text(j)
        if not text:
            raise RuntimeError("OpenAI response contained no text output")
        return text.strip()


def normalize_message(msg: str) -> str:
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
    lines = msg.splitlines()
    subject = lines[0].strip()
    body = "\n".join(lines[1:]).strip()
    args = ["-m", subject]
    if body:
        args += ["-m", body]
    return args


def main() -> int:
    if not inside_git_repo():
        print("LLMCommit: not inside a git repository.", file=sys.stderr)
        return 2

    lang, git_args = split_lang_arg(sys.argv[1:])

    # If user chose interactive commit or explicit message behavior, do not override.
    if should_not_autogenerate(git_args):
        p = subprocess.run(["git", "commit", *git_args])
        return p.returncode

    # Build prompt from what will be committed.
    try:
        ctx = build_git_context(git_args)
    except Exception as e:
        print(f"LLMCommit: {e}", file=sys.stderr)
        return 2

    system = system_instructions(lang)
    user = "Generate a high-quality git commit message for these changes.\n\n" + ctx

    msg = ""
    # 1) Ollama first
    try:
        msg = call_ollama(system, user)
    except Exception:
        msg = ""

    # 2) OpenAI fallback
    if not msg.strip():
        try:
            msg = call_openai(system, user)
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            print(f"LLMCommit: OpenAI HTTP {e.code}: {body or e.reason}", file=sys.stderr)
            return 3
        except Exception as e:
            print(f"LLMCommit: OpenAI call failed: {e}", file=sys.stderr)
            return 3

    msg = normalize_message(msg)
    if not msg:
        print("LLMCommit: failed to generate a commit message.", file=sys.stderr)
        return 3

    # Inject message into git commit args.
    final_args = [*git_args, *message_to_git_m_args(msg)]
    p = subprocess.run(["git", "commit", *final_args])
    return p.returncode


if __name__ == "__main__":
    raise SystemExit(main())
