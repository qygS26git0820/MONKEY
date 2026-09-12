"""路径隔离。机制只有一处（paths.py / policy.py），这里把边界钉死。"""

import unittest

from harness import paths
from harness.tools.policy import PathPolicyError, resolve_in_workspace

from . import support


class EnsureWithinTest(unittest.TestCase):
    def test_project_root_itself_is_allowed(self):
        self.assertEqual(paths.PROJECT_ROOT.resolve(), paths.ensure_within(paths.PROJECT_ROOT))

    def test_inside_project_is_allowed(self):
        self.assertTrue(paths.ensure_within(paths.RUNS_DIR / "some-run"))

    def test_relative_escape_is_rejected(self):
        with self.assertRaises(ValueError):
            paths.ensure_within(paths.PROJECT_ROOT / ".." / "SWE-Agent-outside")

    def test_absolute_outside_is_rejected(self):
        with self.assertRaises(ValueError):
            paths.ensure_within(paths.PROJECT_ROOT.parent)


class ResolveInWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.workspace = self.enterContext(support.scratch_dir("ws"))

    def test_nested_relative_path_resolves_inside(self):
        self.assertEqual((self.workspace / "a" / "b.txt").resolve(),
                         resolve_in_workspace(self.workspace, "a/b.txt"))

    def test_workspace_root_itself_is_allowed(self):
        self.assertEqual(self.workspace.resolve(), resolve_in_workspace(self.workspace, "."))

    def test_parent_traversal_is_denied(self):
        with self.assertRaises(PathPolicyError):
            resolve_in_workspace(self.workspace, "../escape.txt")

    def test_absolute_path_outside_is_denied(self):
        with self.assertRaises(PathPolicyError):
            resolve_in_workspace(self.workspace, str(self.workspace.parent / "elsewhere"))

    def test_empty_and_non_string_are_denied(self):
        for bad in ("", "   ", None, 7):
            with self.subTest(path=bad):
                with self.assertRaises(PathPolicyError):
                    resolve_in_workspace(self.workspace, bad)
