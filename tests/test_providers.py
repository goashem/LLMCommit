"""What LLMCommit sends to each provider, when it retries, and the main() flags that choose a model.

No test reaches the network: urlopen is replaced by a recorder. The module is loaded with no
provider keys, no ~/.llmcommit.json, no project config and none of the OLLAMA_*, OPENAI_*,
GEMINI_*, CLAUDE_*, ANTHROPIC_* or LLMCOMMIT_* variables, so the defaults under test are the code's own.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
"""

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_PREFIXES = ("OLLAMA_", "OPENAI_", "GEMINI_", "CLAUDE_", "ANTHROPIC_", "LLMCOMMIT_")
_HOME = tempfile.mkdtemp(prefix="llmcommit-test-home-")
_ISOLATED = {"HOME": _HOME, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _isolate():
    """Remove every LLMCommit setting from the environment and return what was there."""
    names = [*_ISOLATED, *(name for name in os.environ if name.startswith(_PREFIXES))]
    saved = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    os.environ.update(_ISOLATED)
    return saved


def _restore(saved):
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# Loaded from a directory outside any repository, so no project .llmcommit.json is read either.
_saved, _cwd = _isolate(), os.getcwd()
os.chdir(_HOME)
try:
    _SPEC = importlib.util.spec_from_file_location("LLMCommit", ROOT / "LLMCommit.py")
    LLMCommit = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(LLMCommit)
finally:
    os.chdir(_cwd)
    _restore(_saved)


def setUpModule():
    # Isolate again for the tests themselves: main() and git read the environment at run time, and
    # another test module's tearDownModule may already have put the real one back.
    global _SAVED
    _SAVED = _isolate()


def tearDownModule():
    _restore(_SAVED)
    shutil.rmtree(_HOME, ignore_errors=True)


# --- a recording stand-in for urlopen ------------------------------------------------------------

OPENAI_REPLY = {"choices": [{"message": {"role": "assistant", "content": "Update notes"}}]}


class Reply:
    """The part of an HTTP response that the call_* functions use."""

    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def recorder(reply):
    """Returns (requests, urlopen): each call appends (url, JSON body) and gets reply back."""
    requests = []

    def urlopen(req, timeout=None):
        requests.append((req.full_url, json.loads(req.data)))
        return Reply(reply)

    return requests, urlopen


# --- call_openai() -------------------------------------------------------------------------------

class OpenAIRequest(unittest.TestCase):

    def send(self, model=None):
        """The JSON body call_openai() posts for model (None = the default)."""
        requests, urlopen = recorder(OPENAI_REPLY)
        with (mock.patch.object(LLMCommit, "OPENAI_API_KEY", "placeholder"),
              mock.patch("urllib.request.urlopen", urlopen)):
            self.assertEqual(LLMCommit.call_openai("system", "user", model=model), "Update notes")
        self.assertEqual(len(requests), 1)
        return requests[0][1]

    def test_model_argument_reaches_the_request(self):
        # --openai-model and --model gpt-... arrive here as the model argument.
        self.assertEqual(self.send(model="gpt-4.1-mini")["model"], "gpt-4.1-mini")

    def test_default_model_is_gpt_6_luna(self):
        self.assertEqual(LLMCommit.OPENAI_MODEL, "gpt-6-luna")
        self.assertEqual(self.send()["model"], "gpt-6-luna")

    def test_o_series_gpt_5_and_gpt_6_get_max_completion_tokens(self):
        # Chat Completions reference: max_tokens "is not compatible with o-series models".
        for model in ("o1", "o3-mini", "o4-mini", "gpt-5", "gpt-5-mini", "gpt-5.6-terra", "gpt-6-luna",
                      "gpt-6-astra", "gpt-6.1-sol"):
            with self.subTest(model=model):
                payload = self.send(model)
                self.assertIn("max_completion_tokens", payload)
                self.assertNotIn("max_tokens", payload)

    def test_older_chat_models_keep_max_tokens_and_temperature(self):
        # Control. OpenAI-compatible servers behind OPENAI_BASE_URL may not know max_completion_tokens.
        for model in ("gpt-4o-mini", "gpt-4.1"):
            with self.subTest(model=model):
                payload = self.send(model)
                self.assertEqual((payload.get("max_tokens"), payload.get("temperature")), (220, 0.2))
                self.assertNotIn("max_completion_tokens", payload)
                self.assertNotIn("reasoning_effort", payload)

    def test_reasoning_is_turned_off_where_the_model_allows_it(self):
        # A commit message needs no reasoning, and with reasoning_effort "none" temperature is accepted
        # again (OpenAI: "When reasoning effort is not none, remove temperature, top_p, and top_logprobs").
        for model in ("gpt-6-luna", "gpt-6-sol", "gpt-5.6-terra", "gpt-5.5", "gpt-5.4-mini"):
            with self.subTest(model=model):
                payload = self.send(model)
                self.assertEqual(payload.get("reasoning_effort"), "none")
                self.assertEqual(payload.get("temperature"), 0.2)
                self.assertEqual(payload.get("max_completion_tokens"), 220)

    def test_models_without_effort_none_keep_reasoning_and_get_no_temperature(self):
        # None of these accepts "none" (OpenAI model pages 2026-10-01; gpt-6-astra answers HTTP 400), and a
        # reasoning model rejects temperature. They keep their default effort and get room for it.
        for model in ("o3-mini", "gpt-5", "gpt-5-mini", "gpt-5.2-pro", "gpt-6-astra", "gpt-6.1-sol"):
            with self.subTest(model=model):
                payload = self.send(model)
                self.assertNotIn("reasoning_effort", payload)
                self.assertNotIn("temperature", payload)
                self.assertEqual(payload.get("max_completion_tokens"), 2000)


# --- call_ollama() -------------------------------------------------------------------------------

OLLAMA_REPLY = {"message": {"role": "assistant", "content": "Update notes"}}


class OllamaRequest(unittest.TestCase):

    def send(self, model=None):
        """(url, JSON body) that call_ollama() posts for model (None = the default)."""
        requests, urlopen = recorder(OLLAMA_REPLY)
        with mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(LLMCommit.call_ollama("system", "user", model=model), "Update notes")
        self.assertEqual(len(requests), 1)
        return requests[0]

    def test_thinking_is_turned_off(self):
        # qwen3 thinks by default. A commit message does not need it, and on a local machine it costs time.
        # Ollama: think false = "request no thinking output, if the model permits it".
        url, payload = self.send()
        self.assertTrue(url.endswith("/api/chat"))
        self.assertIs(payload.get("think"), False)

    def test_default_model_is_qwen3_8b(self):
        self.assertEqual(LLMCommit.OLLAMA_MODEL, "qwen3:8b")
        self.assertEqual(self.send()[1]["model"], "qwen3:8b")


# --- retry_with_backoff() ------------------------------------------------------------------------

def http_error(code):
    return urllib.error.HTTPError("http://localhost:11434/api/chat", code, f"HTTP {code}", {}, io.BytesIO(b"{}"))


class Retries(unittest.TestCase):
    """Only transient failures (429, 5xx) are retried. Anything else hands over to the next provider at once."""

    def attempts(self, *outcomes):
        """retry_with_backoff() over outcomes (an exception is raised, anything else returned).

        Returns (the result or the exception raised, number of calls, number of sleeps)."""
        calls = []

        def func():
            outcome = outcomes[len(calls)]
            calls.append(outcome)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with mock.patch.object(LLMCommit.time, "sleep") as sleep:
            try:
                result = LLMCommit.retry_with_backoff(func)
            except Exception as e:
                result = e
        return result, len(calls), sleep.call_count

    def test_ollama_model_not_found_is_tried_once(self):
        # Ollama answers 404 for a model that is not pulled. It is first in the pipeline, so three attempts
        # would hold up every commit by the 1 s + 2 s backoff before the next provider is tried.
        urlopen = mock.Mock(side_effect=http_error(404))
        with (mock.patch("urllib.request.urlopen", urlopen),
              mock.patch.object(LLMCommit.time, "sleep") as sleep):
            with self.assertRaises(urllib.error.HTTPError):
                LLMCommit.retry_with_backoff(lambda: LLMCommit.call_ollama("system", "user"))
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

    def test_client_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            with self.subTest(code=code):
                result, calls, sleeps = self.attempts(*[http_error(code)] * 3)
                self.assertEqual((getattr(result, "code", result), calls, sleeps), (code, 1, 0))

    def test_connection_errors_are_not_retried(self):
        # A refused connection (Ollama not running) is not a 429 or a 5xx either.
        refused = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
        result, calls, sleeps = self.attempts(refused, refused, refused)
        self.assertEqual((result, calls, sleeps), (refused, 1, 0))

    def test_rate_limit_and_server_errors_are_retried(self):
        for code in (429, 500, 502, 503):
            with self.subTest(code=code):
                self.assertEqual(self.attempts(http_error(code), "Update notes"), ("Update notes", 2, 1))

    def test_gives_up_after_three_attempts(self):
        result, calls, sleeps = self.attempts(*[http_error(503)] * 3)
        self.assertEqual((getattr(result, "code", result), calls, sleeps), (503, 3, 2))


# --- call_gemini() and call_claude() -------------------------------------------------------------

GEMINI_REPLY = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Update notes"}]}}]}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "Update notes"}]}


class GeminiRequest(unittest.TestCase):

    def send(self):
        requests, urlopen = recorder(GEMINI_REPLY)
        with (mock.patch.object(LLMCommit, "GEMINI_API_KEY", "placeholder"),
              mock.patch("urllib.request.urlopen", urlopen)):
            self.assertEqual(LLMCommit.call_gemini("system", "user"), "Update notes")
        self.assertEqual(len(requests), 1)
        return requests[0]

    def test_default_model_is_gemini_3_5_flash_lite(self):
        self.assertEqual(LLMCommit.GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertIn("/models/gemini-3.5-flash-lite:generateContent", self.send()[0])

    def test_minimal_thinking_and_no_temperature(self):
        # Gemini 3.x deprecated temperature on 2026-07-21. Thinking counts against maxOutputTokens, so the
        # limit leaves room for it.
        config = self.send()[1]["generationConfig"]
        self.assertNotIn("temperature", config)
        self.assertEqual(config.get("thinkingConfig"), {"thinkingLevel": "MINIMAL"})
        self.assertEqual(config.get("maxOutputTokens"), 1024)


CLAUDE_THINKING_REPLY = {"content": [{"type": "thinking", "thinking": "Summarise the diff.", "signature": "sig"},
                                     {"type": "text", "text": "Update notes"}]}


class ClaudeRequest(unittest.TestCase):

    def send(self, model=None, reply=CLAUDE_REPLY, api_key="placeholder", oauth_token=""):
        """(urllib Request, JSON body, return value) of one call_claude() call."""
        sent = []

        def urlopen(req, timeout=None):
            sent.append(req)
            return Reply(reply)

        with (mock.patch.object(LLMCommit, "ANTHROPIC_API_KEY", api_key),
              mock.patch.object(LLMCommit, "CLAUDE_OAUTH_TOKEN", oauth_token),
              mock.patch("urllib.request.urlopen", urlopen)):
            text = LLMCommit.call_claude("system", "user", model=model)
        return sent[0], json.loads(sent[0].data), text

    def test_default_model_is_claude_haiku_5_5_with_thinking_off(self):
        # Haiku 5.5 thinks by default, and thinking counts against max_tokens, so a short limit could
        # end before any text. Haiku 5.5 accepts thinking disabled.
        self.assertEqual(LLMCommit.CLAUDE_MODEL, "claude-haiku-5-5")
        _, payload, text = self.send()
        self.assertEqual(text, "Update notes")
        self.assertEqual(payload["model"], "claude-haiku-5-5")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["max_tokens"], 300)
        self.assertNotIn("temperature", payload)

    def test_only_haiku_5_gets_the_thinking_field(self):
        # Haiku 4.5 does not think unless asked; Sonnet 5.5 and Opus 5.5 reject thinking disabled with a 400.
        for model in ("claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"):
            with self.subTest(model=model):
                self.assertNotIn("thinking", self.send(model=model)[1])

    def test_text_is_read_past_a_thinking_block(self):
        self.assertEqual(self.send(reply=CLAUDE_THINKING_REPLY)[2], "Update notes")

    def test_api_key_wins_over_the_oauth_token(self):
        req = self.send(api_key="placeholder", oauth_token="oauth-placeholder")[0]
        self.assertEqual(req.get_header("X-api-key"), "placeholder")
        self.assertIsNone(req.get_header("Authorization"))

    def test_oauth_token_is_used_only_without_an_api_key(self):
        req = self.send(api_key="", oauth_token="oauth-placeholder")[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer oauth-placeholder")
        self.assertIsNone(req.get_header("X-api-key"))


# --- defaults and the places that document them --------------------------------------------------

def readme_env_defaults():
    """{NAME: default} from the README's environment variable table (rows with a `code` default)."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return dict(re.findall(r"(?m)^\|\s*`([A-Z_]+)`\s*\|\s*`([^`]*)`", text))


def readme_config_example():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    return json.loads(re.search(r"(?s)### Config files.*?```json\n(.*?)```", text).group(1))


def header_comment_values():
    """{NAME: value} from the '#   NAME=value' lines at the top of LLMCommit.py."""
    head = (ROOT / "LLMCommit.py").read_text(encoding="utf-8").split("\nfrom __future__", 1)[0]
    return dict(re.findall(r"(?m)^#\s+([A-Z_]+)=(\S+)", head))


class Defaults(unittest.TestCase):

    def test_pipeline_tries_ollama_first_and_the_rest_in_their_old_order(self):
        self.assertEqual(LLMCommit.PROVIDER_ORDER, ["ollama", "openai", "claude", "gemini"])

    def test_readme_environment_table_matches_the_code(self):
        rows = readme_env_defaults()
        for name, value in {"OLLAMA_MODEL": LLMCommit.OLLAMA_MODEL, "OPENAI_MODEL": LLMCommit.OPENAI_MODEL,
                            "GEMINI_MODEL": LLMCommit.GEMINI_MODEL, "CLAUDE_MODEL": LLMCommit.CLAUDE_MODEL,
                            "LLMCOMMIT_PROVIDERS": ",".join(LLMCommit.PROVIDER_ORDER)}.items():
            with self.subTest(name=name):
                self.assertEqual(rows.get(name), value)

    def test_readme_config_example_uses_the_default_models(self):
        example = readme_config_example()
        for key, value in {"ollama_model": LLMCommit.OLLAMA_MODEL, "openai_model": LLMCommit.OPENAI_MODEL,
                           "claude_model": LLMCommit.CLAUDE_MODEL, "gemini_model": LLMCommit.GEMINI_MODEL}.items():
            with self.subTest(key=key):
                self.assertEqual(example.get(key), value)

    def test_header_comment_matches_the_code(self):
        values = header_comment_values()
        for name in ("OLLAMA_MODEL", "OPENAI_MODEL", "GEMINI_MODEL", "CLAUDE_MODEL"):
            with self.subTest(name=name):
                self.assertEqual(values.get(name), getattr(LLMCommit, name))

    def test_main_docstring_lists_the_default_order(self):
        listed = re.findall(r"(?m)^\s*\d+\.\s+(\w+)", LLMCommit.main.__doc__)
        self.assertEqual([name.lower() for name in listed], LLMCommit.PROVIDER_ORDER)

    def test_readme_lists_only_flags_that_skip_generation(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        listed = re.search(r"(?s)## When it won't generate a message\n\nIf you pass (.*?), the tool runs", text).group(1)
        flags = re.findall(r"`(-[^`]+)`", listed)
        self.assertTrue(flags)
        for flag in flags:
            with self.subTest(flag=flag):
                self.assertTrue(LLMCommit.should_not_autogenerate([flag]))


# --- main() --------------------------------------------------------------------------------------

def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


class TempRepo(unittest.TestCase):
    """A throwaway repository with one commit and one uncommitted change, as the cwd of main()."""

    def setUp(self):
        self.cwd = os.getcwd()
        self.repo = tempfile.mkdtemp(prefix="llmcommit-test-repo-")
        self.no_hooks = tempfile.mkdtemp(prefix="llmcommit-test-hooks-")
        os.chdir(self.repo)
        git("init", "-q", "-b", "main")
        git("config", "user.name", "LLMCommit Test")
        git("config", "user.email", "test@example.invalid")
        git("config", "core.hooksPath", self.no_hooks)
        write("notes/todo.md", "# Tehtävät\n- [ ] Soita Kapsiin\n")
        git("add", "-A")
        git("commit", "-q", "-m", "init")
        write("notes/todo.md", "# Tehtävät\n- [x] Soita Kapsiin\n")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.no_hooks, ignore_errors=True)

    def run_main(self, *args, providers=("openai",)):
        """Runs main() with a recording urlopen; returns (exit code, recorded requests)."""
        requests, urlopen = recorder(OPENAI_REPLY)
        with (mock.patch.object(LLMCommit, "PROVIDER_ORDER", list(providers)),
              mock.patch.object(LLMCommit, "OPENAI_API_KEY", "placeholder"),
              mock.patch("urllib.request.urlopen", urlopen),
              mock.patch.object(sys, "argv", ["llmcommit", *args])):
            rc = LLMCommit.main()
        return rc, requests


class ModelFlags(TempRepo):

    def test_openai_model_flag_reaches_the_request(self):
        rc, requests = self.run_main("-a", "--openai-model", "gpt-4.1-mini")
        self.assertEqual(rc, 0)
        self.assertEqual([body["model"] for _url, body in requests], ["gpt-4.1-mini"])

    def test_model_flag_with_a_gpt_name_reaches_the_openai_request(self):
        rc, requests = self.run_main("-a", "--model", "gpt-4.1-mini")
        self.assertEqual(rc, 0)
        self.assertEqual([body["model"] for _url, body in requests], ["gpt-4.1-mini"])


class ReviewFlag(TempRepo):
    """--interactive is LLMCommit's alias of --review, not git's interactive staging."""

    def test_interactive_is_not_a_reason_to_skip_generation(self):
        self.assertFalse(LLMCommit.should_not_autogenerate(["-a", "--interactive"]))
        # Control: interactive staging still passes through to git.
        for flag in ("-p", "--patch"):
            with self.subTest(flag=flag):
                self.assertTrue(LLMCommit.should_not_autogenerate(["-a", flag]))

    def test_interactive_opens_the_generated_message_in_the_editor(self):
        editor_dir = tempfile.mkdtemp(prefix="llmcommit-test-editor-")
        self.addCleanup(shutil.rmtree, editor_dir, ignore_errors=True)
        editor = Path(editor_dir) / "editor.sh"
        editor.write_text('#!/bin/sh\nprintf "Reviewed: %s\\n" "$(head -n 1 "$1")" > "$1.new" && mv "$1.new" "$1"\n')
        editor.chmod(0o755)
        real_run = subprocess.run

        def run(cmd, *args, **kwargs):
            # git's own --interactive would wait for input on the terminal: fail instead.
            if list(cmd[:2]) == ["git", "commit"] and "--interactive" in cmd:
                raise AssertionError(f"--interactive was passed to git: {cmd}")
            return real_run(cmd, *args, **kwargs)

        with (mock.patch.object(LLMCommit.subprocess, "run", run),
              mock.patch.dict(os.environ, {"EDITOR": str(editor)})):
            rc, requests = self.run_main("-a", "--interactive")
        self.assertEqual(rc, 0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(git("log", "-1", "--format=%s").strip(), "Reviewed: Update notes")


class IncludeFlag(TempRepo):
    """-i is git's short form of --include: commit what is staged plus the given paths."""

    CHANGE = "+- [x] Soita Kapsiin"  # the uncommitted change TempRepo leaves in notes/todo.md

    def test_short_and_long_form_are_read_alike(self):
        for flag in ("-i", "--include"):
            with self.subTest(flag=flag):
                args = [flag, "notes/todo.md"]
                self.assertFalse(LLMCommit.should_not_autogenerate(args))
                self.assertIn(self.CHANGE, LLMCommit.build_git_context(args))

    def test_include_generates_the_message_without_opening_an_editor(self):
        editor_dir = tempfile.mkdtemp(prefix="llmcommit-test-editor-")
        self.addCleanup(shutil.rmtree, editor_dir, ignore_errors=True)
        opened = Path(editor_dir) / "editor-was-opened"
        editor = Path(editor_dir) / "editor.sh"
        editor.write_text(f'#!/bin/sh\ntouch "{opened}"\nexit 1\n')
        editor.chmod(0o755)
        with mock.patch.dict(os.environ, {"GIT_EDITOR": str(editor)}):
            rc, requests = self.run_main("-i", "notes/todo.md")
        self.assertFalse(opened.exists(), "git opened the editor: no message was generated")
        self.assertEqual(rc, 0)
        self.assertEqual(len(requests), 1)
        self.assertIn(self.CHANGE, requests[0][1]["messages"][1]["content"])
        self.assertEqual(git("log", "-1", "--format=%s").strip(), "Update notes")


if __name__ == "__main__":
    unittest.main()
