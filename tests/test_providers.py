"""What LLMCommit sends to each provider, when it retries, and the main() flags that choose a model.

No test reaches the network: urlopen is replaced by a recorder. The module is loaded with no
provider keys, no ~/.llmcommit.json, no project config and none of the OLLAMA_*, OPENAI_*,
GEMINI_*, CLAUDE_*, ANTHROPIC_* or LLMCOMMIT_* variables, so the defaults under test are the code's own.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
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
                           "gemini_model": LLMCommit.GEMINI_MODEL}.items():
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


if __name__ == "__main__":
    unittest.main()
