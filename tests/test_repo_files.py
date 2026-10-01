"""Repository files whose mistakes fail silently: a broken .gitignore line just stops matching.

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
"""

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ignoring_rule(path):
    """(source, pattern) of the rule that ignores path, or None.

    Only the repository's own rules count: the index (tracked files) and the global excludes file
    are left out, so the answer does not depend on the machine.
    """
    p = subprocess.run(["git", "-C", str(ROOT), "-c", f"core.excludesFile={os.devnull}",
                        "check-ignore", "--no-index", "-v", path], capture_output=True, text=True)
    if p.returncode == 1:
        return None
    if p.returncode != 0:
        raise AssertionError(f"git check-ignore failed: {p.stderr.strip()}")
    source, _line, pattern = p.stdout.split("\t", 1)[0].split(":", 2)
    return source, pattern


class GitIgnore(unittest.TestCase):

    def test_done_md_and_pycache_are_separate_rules(self):
        # Appending to a file without a final newline once glued the two into "/DONE.md__pycache__/",
        # a rule that matches neither.
        self.assertEqual(ignoring_rule("DONE.md"), (".gitignore", "/DONE.md"))
        for path in ("__pycache__/notes.txt", "tests/__pycache__/notes.txt"):
            with self.subTest(path=path):
                self.assertEqual(ignoring_rule(path), (".gitignore", "__pycache__/"))

    def test_source_is_not_ignored(self):
        # Control: the helper does report "not ignored".
        self.assertIsNone(ignoring_rule("LLMCommit.py"))


if __name__ == "__main__":
    unittest.main()
