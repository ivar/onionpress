#!/usr/bin/env python3
"""The development branch publishes dev-prefixed images; main must not.

.github/workflows/docker-publish.yml on the `development` branch sets
IMAGE_PREFIX to "dev-", so every image a run from that branch pushes
(ghcr.io/brewsterkahle/dev-onionpress-tor, -wordpress, -stress-worker) lands
beside the release images that shipped installs pull, never on top of them.
On main the prefix must be empty, and nothing in a plain
`git merge development` resets it: the merged workflow would publish dev-*
images on the next release while docker-compose.yml, both launchers and
build/image-pins.env kept pulling the old onionpress-* digests.

So, when CI is running for main — a push to it, or a pull request into it —
the prefix has to be empty; when it is running for development, the prefix
has to be "dev-". Locally, with no CI variables set, only the structural
checks run: the prefix is declared once and every image reference goes
through it, so that changing the one line really changes every image.

No PyYAML: CI installs nothing beyond CPython, so the workflow is read with
regexes, like tests/test_image_pins.py does for docker-compose.yml.
"""

import os
import re
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

WORKFLOW = ".github/workflows/docker-publish.yml"
OWNER = "brewsterkahle/"
PREFIX_EXPR = "${{ env.IMAGE_PREFIX }}"
IMAGES = ("stress-worker", "tor", "wordpress")

# What each branch's copy of the workflow must publish under.
EXPECTED_PREFIX = {
    "main": "",
    "development": "dev-",
}


def _read(rel_path):
    with open(os.path.join(PROJECT_ROOT, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def _code(text):
    """Workflow text with `#` comment lines removed.

    The header explains the trap by naming the bare image names, so scanning
    the raw text would match the explanation instead of the instruction.
    """
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )


def _image_prefix(text):
    """Value of the top-level `IMAGE_PREFIX:` env entry, or None if absent.

    Accepts the bare, "double-quoted" and 'single-quoted' spellings, and an
    empty value written either as `IMAGE_PREFIX:` or `IMAGE_PREFIX: ""`.
    """
    m = re.search(r"^  IMAGE_PREFIX:[ \t]*(.*?)[ \t]*$", _code(text), re.MULTILINE)
    if not m:
        return None
    value = m.group(1)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _ci_branch():
    """The branch this CI run is for: the PR's base, else the pushed ref.

    GitHub sets GITHUB_BASE_REF only for pull_request events, where
    GITHUB_REF_NAME is the synthetic "<n>/merge" ref. Empty outside CI.
    """
    return os.environ.get("GITHUB_BASE_REF") or os.environ.get("GITHUB_REF_NAME") or ""


class DevImagePrefixTest(unittest.TestCase):
    def setUp(self):
        self.text = _read(WORKFLOW)

    def test_prefix_is_declared_once(self):
        code = _code(self.text)
        declarations = re.findall(r"^  IMAGE_PREFIX:", code, re.MULTILINE)
        self.assertEqual(
            len(declarations), 1,
            f"{WORKFLOW}: expected exactly one top-level `IMAGE_PREFIX:` under "
            f"env:, found {len(declarations)}")

    def test_every_image_reference_goes_through_the_prefix(self):
        code = _code(self.text)
        bare = [line.strip() for line in code.splitlines()
                if OWNER + "onionpress-" in line]
        self.assertEqual(
            bare, [],
            f"{WORKFLOW}: image references that bypass IMAGE_PREFIX, so the "
            f"one-line switch would not rename them:\n  " + "\n  ".join(bare))
        routed = re.findall(
            re.escape(OWNER + PREFIX_EXPR + "onionpress-") + r"([a-z-]+):", code)
        self.assertEqual(
            tuple(sorted(set(routed))), IMAGES,
            f"{WORKFLOW}: images routed through IMAGE_PREFIX are "
            f"{sorted(set(routed))}, expected {list(IMAGES)}")

    def test_prefix_matches_the_branch_ci_runs_for(self):
        branch = _ci_branch()
        if branch not in EXPECTED_PREFIX:
            self.skipTest(
                f"CI is running for {branch!r}, not main or development"
                if branch else "not running in CI (GITHUB_REF_NAME unset)")
        expected = EXPECTED_PREFIX[branch]
        actual = _image_prefix(self.text)
        self.assertEqual(
            actual, expected,
            f"{WORKFLOW} sets IMAGE_PREFIX to {actual!r}, but this run is for "
            f"the {branch} branch, which must publish with prefix "
            f"{expected!r}. "
            + ("A merge of development into main carries \"dev-\" along: "
               "set IMAGE_PREFIX to \"\" in the merge commit."
               if branch == "main" else
               "The development branch must never publish over the release "
               "images: set IMAGE_PREFIX back to \"dev-\"."))


if __name__ == "__main__":
    unittest.main()
