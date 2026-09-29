"""Secret redaction in LLMCommit: sanitize_text() and the prompt that leaves the machine.

Every key in this file is synthetic and assembled at runtime from fragments, so the source
itself does not look like a leaked credential to secret scanners.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
"""

import importlib.util
import os
import random
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# LLMCommit reads ~/.llmcommit.json and the provider keys when it is imported, and main() runs
# `git commit`. Isolate both before loading it: no real config, no global git hooks, and no key
# that could reach a provider.
_ISOLATED = {"HOME": tempfile.mkdtemp(prefix="llmcommit-test-home-"),
             "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
_REMOVED = ("OPENAI_API_KEY", "GEMINI_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
            "LLMCOMMIT_PROVIDERS", "LLMCOMMIT_DEBUG")
_SAVED = {name: os.environ.get(name) for name in (*_ISOLATED, *_REMOVED)}
os.environ.update(_ISOLATED)
for _name in _REMOVED:
    os.environ.pop(_name, None)

_SPEC = importlib.util.spec_from_file_location("LLMCommit", Path(__file__).resolve().parents[1] / "LLMCommit.py")
LLMCommit = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(LLMCommit)
sanitize = LLMCommit.sanitize_text


def tearDownModule():
    shutil.rmtree(_ISOLATED["HOME"], ignore_errors=True)
    for name, value in _SAVED.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


# --- synthetic secrets -------------------------------------------------------------------------

ALNUM = string.ascii_letters + string.digits
URLSAFE = ALNUM + "-_"
BASE64 = ALNUM + "+/"


def fake(length, alphabet=ALNUM, seed=""):
    """Random-looking but deterministic, so every run tests the same strings."""
    rng = random.Random(f"{seed}:{length}")
    return "".join(rng.choice(alphabet) for _ in range(length))


OPENAI_LEGACY = "sk-" + fake(48, seed="legacy")
OPENAI_PROJECT = "sk-" + "proj-" + fake(156, URLSAFE, "proj")
OPENAI_SVCACCT = "sk-" + "svcacct-" + fake(120, URLSAFE, "svcacct")
OPENAI_ADMIN = "sk-" + "admin-" + fake(100, URLSAFE, "admin")
ANTHROPIC_API = "sk-" + "ant-api03-" + fake(93, URLSAFE, "api03") + "AA"
ANTHROPIC_OAUTH = "sk-" + "ant-oat01-" + fake(93, URLSAFE, "oat01") + "AA"
AWS_AKIA = "AK" + "IA" + fake(16, string.ascii_uppercase + string.digits, "akia")
AWS_ASIA = "AS" + "IA" + fake(16, string.ascii_uppercase + string.digits, "asia")
GOOGLE = "AI" + "za" + fake(35, ALNUM, "google")
GITHUB = {kind: kind + "_" + fake(36, seed=kind) for kind in ("ghp", "gho", "ghu", "ghs", "ghr")}
GITHUB_FINE = "github" + "_pat_" + fake(22, seed="pat-a") + "_" + fake(59, seed="pat-b")
OPAQUE = fake(32, "0123456789abcdef", "opaque")  # no telltale prefix: only its name gives it away
PASSWORD = "Kissa" + fake(9, seed="password")


def private_key(label, seed="pem", lines=6):
    """A PEM-style block with a random body. Returns (block, body lines)."""
    body = [fake(64, BASE64, f"{seed}{i}") for i in range(lines)] + [fake(22, BASE64, seed) + "=="]
    return "\n".join([f"-----BEGIN {label}-----", *body, f"-----END {label}-----"]), body


def as_added(text):
    return "\n".join("+" + line for line in text.splitlines())


# --- sanitize_text() -----------------------------------------------------------------------------

class RedactsSecrets(unittest.TestCase):
    """Every format is checked as plain text and as added lines of a diff."""

    def assertRedacted(self, cases):
        for text, secrets in cases:
            for variant in (text, as_added(text)):
                with self.subTest(text=variant[:48]):
                    out = sanitize(variant)
                    self.assertIn("[REDACTED]", out)
                    for secret in secrets:
                        self.assertNotIn(secret, out)

    def test_openai_project_and_other_new_key_formats(self):
        self.assertRedacted([(template.format(key), [key])
                             for key in (OPENAI_PROJECT, OPENAI_SVCACCT, OPENAI_ADMIN)
                             for template in ("{}", 'OPENAI_API_KEY="{}"', "Authorization: Bearer {}")])

    def test_anthropic_keys(self):
        self.assertRedacted([(template.format(key), [key])
                             for key in (ANTHROPIC_API, ANTHROPIC_OAUTH)
                             for template in ("{}", "x-api-key: {}", "export CLAUDE_CODE_OAUTH_TOKEN={}")])

    def test_unquoted_assignment_whose_name_ends_in_a_secret_word(self):
        names = ("OPENAI_API_KEY=", "export ANTHROPIC_API_KEY=", "GEMINI_API_KEY = ", "CLAUDE_CODE_OAUTH_TOKEN=",
                 "DB_PASSWORD=", "client_secret: ", "SECRET_KEY=", "aws_secret_access_key = ", "apiKey: ")
        self.assertRedacted([(name + OPAQUE, [OPAQUE]) for name in names])

    def test_quoted_names_in_json_and_dicts(self):
        self.assertRedacted([
            (f'"api_key": "{OPAQUE}"', [OPAQUE]),
            (f'{{"password": "{PASSWORD}"}}', [PASSWORD]),
            (f"{{'token': '{OPAQUE}'}}", [OPAQUE]),
        ])

    def test_markdown_and_finnish_labels(self):
        self.assertRedacted([
            (f"**Salasana:** {PASSWORD}", [PASSWORD]),
            (f"**Password**: {PASSWORD}", [PASSWORD]),
            (f"- API-avain: {OPAQUE}", [OPAQUE]),
            (f"SSH-avaimen passphrase: {PASSWORD}", [PASSWORD]),
        ])

    def test_private_key_blocks(self):
        labels = ("RSA PRIVATE KEY", "OPENSSH PRIVATE KEY", "PRIVATE KEY", "ENCRYPTED PRIVATE KEY",
                  "PGP PRIVATE KEY BLOCK")
        self.assertRedacted([private_key(label, seed=label) for label in labels])

    def test_key_lines_without_begin_or_end_in_the_hunk(self):
        # An edit just below a key pasted into a note: the last key lines reach the diff as context.
        _, body = private_key("OPENSSH PRIVATE KEY", seed="hunk")
        full_lines = body[-4:-1]  # 64 characters each; the short last line is not covered
        hunk = "\n".join(["@@ -12,3 +12,4 @@", *(" " + line for line in full_lines), "+Avain kierretty 29.9."])
        out = sanitize(hunk)
        for line in full_lines:
            self.assertNotIn(line, out)
        self.assertIn("+Avain kierretty 29.9.", out)

    def test_github_token_types(self):
        self.assertRedacted([(f"GH_AUTH={token}", [token]) for token in (*GITHUB.values(), GITHUB_FINE)])

    def test_old_patterns_still_work(self):
        self.assertRedacted([
            (f"aws_access_key_id = {AWS_AKIA}", [AWS_AKIA]),
            (f"aws_session = {AWS_ASIA}", [AWS_ASIA]),
            (f"key: {OPENAI_LEGACY}", [OPENAI_LEGACY]),
            (f"maps: {GOOGLE}", [GOOGLE]),
            (f'api_key = "{OPAQUE}"', [OPAQUE]),
            (f"password: '{PASSWORD}'", [PASSWORD]),
            (f'token="{OPAQUE}"', [OPAQUE]),
        ])


class LeavesOrdinaryTextAlone(unittest.TestCase):

    def test_code_and_prose(self):
        cases = ("sk-learn", "pip install scikit-learn", "disk-space-monitoring-dashboard-config",
                 "task-management-and-planning-notes-2026", "token = 5", "max_tokens = 2000",
                 '"max_tokens": max_tokens,', "token_count = 12345678", "password_hint",
                 'password_hint = "Ensimmäisen lemmikin nimi"', 'password = ""', "if not OPENAI_API_KEY:",
                 "secrets: inherit", "tags: [ohjelmointi, tietoturva]",
                 "Avaimet ovat kansiossa avaimet/, kierto on kuvattu erikseen.")
        for text in cases:
            for variant in (text, "+" + text):
                with self.subTest(text=variant):
                    self.assertEqual(sanitize(variant), variant)

    def test_ordinary_diff(self):
        diff = ("diff --git a/notes/todo.md b/notes/todo.md\n"
                "index 3b18e51..a9c4f2d 100644\n"
                "--- a/notes/todo.md\n"
                "+++ b/notes/todo.md\n"
                "@@ -1,3 +1,5 @@\n"
                " # Tehtävät\n"
                "-- [ ] Soita Kapsiin\n"
                "+- [x] Soita Kapsiin\n"
                "+- [ ] Päivitä avainten kierto (ks. avaimet/README.md)\n"
                "+def build_git_context(args: List[str], max_chars: int = 14000) -> str:\n")
        self.assertEqual(sanitize(diff), diff)


# --- the prompt main() sends ---------------------------------------------------------------------

def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


class OutboundPrompt(unittest.TestCase):
    """main() as kapsisync.sh and commitfolders.sh run it (-a --addall), with the provider faked."""

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
        write("avaimet/openai.env", f"OPENAI_API_KEY={OPENAI_LEGACY}\n")
        git("add", "-A")
        git("commit", "-q", "-m", "init")

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.no_hooks, ignore_errors=True)

    def run_main(self, *args):
        prompts = []

        def fake_openai(system, user, timeout_s=None, model=None):
            prompts.append(system + "\n" + user)
            return "Update notes"

        with (mock.patch.object(LLMCommit, "PROVIDER_ORDER", ["openai"]),
              mock.patch.object(LLMCommit, "OPENAI_API_KEY", "placeholder"),
              mock.patch.object(LLMCommit, "call_openai", fake_openai),
              mock.patch("urllib.request.urlopen", side_effect=AssertionError("network call in a test")),
              mock.patch.object(sys, "argv", ["llmcommit", *args])):
            rc = LLMCommit.main()
        self.assertEqual(len(prompts), 1)
        return rc, prompts[0]

    def test_addall_prompt_contains_no_secret(self):
        write("notes/todo.md", "# Tehtävät\n- [x] Soita Kapsiin\n- [ ] Päivitä avainten kierto\n")
        write("avaimet/openai.env", f"OPENAI_API_KEY={OPENAI_PROJECT}\nANTHROPIC_API_KEY={ANTHROPIC_API}\n"
                                    f"GEMINI_API_KEY={OPAQUE}\n")
        block, body = private_key("OPENSSH PRIVATE KEY", seed="e2e")
        write("avaimet/palvelimet.md", f"# Palvelimet\n\n**Salasana:** {PASSWORD}\n\n```\n{block}\n```\n")
        rc, prompt = self.run_main("-a", "--addall")
        self.assertEqual(rc, 0)
        # Positive controls: the changed file and the untracked one --addall picked up are in the prompt.
        self.assertIn("Päivitä avainten kierto", prompt)
        self.assertIn("# Palvelimet", prompt)
        for secret in (OPENAI_LEGACY, OPENAI_PROJECT, ANTHROPIC_API, OPAQUE, PASSWORD, *body):
            with self.subTest(secret=secret[:16]):
                self.assertNotIn(secret, prompt)

    def test_file_names_in_status_are_redacted(self):
        # A format the old patterns already knew, so this isolates the name-status and porcelain channels.
        token = GITHUB["ghp"]
        write(f"avaimet/{token}.txt", "vanha avain\n")
        rc, prompt = self.run_main("-a", "--addall")
        self.assertEqual(rc, 0)
        self.assertIn("vanha avain", prompt)
        self.assertNotIn(token, prompt)

    def test_diff_is_redacted_before_truncation(self):
        # Cut the diff in the middle of a key: redaction has to see the whole key first.
        write("notes/todo.md", "x\n" * 200 + f"key: {OPENAI_LEGACY}\n" + "y\n" * 200)
        raw = git("diff", "--no-color", "HEAD")
        context = LLMCommit.build_git_context(["-a"], max_chars=raw.index(OPENAI_LEGACY) + 12)
        self.assertIn("[DIFF TRUNCATED]", context)
        self.assertNotIn(OPENAI_LEGACY[:12], context)


if __name__ == "__main__":
    unittest.main()
