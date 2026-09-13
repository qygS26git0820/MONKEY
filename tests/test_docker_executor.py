"""容器后端：单元断言常跑，真起容器的断言在本地没有镜像时整类跳过。

不装 docker 的机器仍能跑完整套件——这正是 image_present() 存在的理由。
反过来，只要本地有 python:3.12-slim，这批断言就必须为真。
"""

import os
import subprocess
import sys
import unittest

from harness.agent.scripted import ScriptedAgent
from harness.env.docker import DEFAULT_IMAGE, DockerExecutor, image_present
from harness.env.expand import expand_command
from harness.env.local import LocalExecutor
from harness.tasks.loader import load_task
from harness.trace import read_trace, validate_records

from . import support

# 与 tests/test_scripted_controls.py 同一张表。不 import 它，因为那张表是
# 阶段 1 冻结语料的断言，这张表是"换后端后标签不变"的断言，两者将来可能分叉。
CONTROLS = (
    ("toy-001", "scripted_ok", None, "none"),
    ("toy-002", "scripted_ok", None, "none"),
    ("toy-001", "scripted_bad_edit", None, "verification_failed"),
    ("toy-001", "scripted_ok", "repo_faulty", "verification_failed"),
    ("toy-001", "scripted_tool_error", None, "tool_error_repeated"),
    ("toy-001", "scripted_denied", None, "policy_denied"),
    ("toy-001", "scripted_gave_up", None, "agent_gave_up"),
    ("toy-001", "scripted_loop_limit", None, "agent_loop_limit"),
)


def docker_config(**kwargs):
    """同一把尺子：budgets 与 default.toml 相同，只换后端。"""
    kwargs.setdefault("wall_timeout_s", 180.0)
    return support.make_config(executor_kind="docker",
                              docker_image=DEFAULT_IMAGE, **kwargs)


class ExpandCommandTest(unittest.TestCase):
    def test_python_placeholder_resolves_per_backend(self):
        with support.scratch_dir() as scratch:
            spec = ["{python}", "-m", "unittest", "discover"]
            self.assertEqual([sys.executable, "-m", "unittest", "discover"],
                             expand_command(spec, LocalExecutor(scratch)))
            self.assertEqual(["python", "-m", "unittest", "discover"],
                             expand_command(spec, DockerExecutor(scratch)))

    def test_unknown_placeholder_is_passed_through_untouched(self):
        with support.scratch_dir() as scratch:
            spec = ["{python}", "{workspace}", "--flag"]
            self.assertEqual([sys.executable, ".", "--flag"],
                             expand_command(spec, LocalExecutor(scratch)))


class VisiblePathTest(unittest.TestCase):
    def test_two_backends_disagree_on_the_same_path(self):
        # 这不是缺陷，是事实：agent 在两种后端里看到的世界本来就不同。
        # 阶段 1 记 "workspace/..."，容器里是 "/workspace/..."。
        with support.scratch_dir() as scratch:
            workspace = scratch / "workspace"
            workspace.mkdir()
            local = LocalExecutor(scratch)
            docker = DockerExecutor(workspace)
            self.assertEqual("workspace", local.visible_path(workspace))
            self.assertEqual("workspace/a.py", local.visible_path(workspace / "a.py"))
            self.assertEqual("/workspace", docker.visible_path(workspace))
            self.assertEqual("/workspace/a.py", docker.visible_path(workspace / "a.py"))

    def test_outside_workspace_is_not_dressed_up_as_visible(self):
        # 挂载点之外的东西容器里根本看不到。如实返回宿主路径，不假装可见。
        with support.scratch_dir() as scratch:
            workspace = scratch / "workspace"
            workspace.mkdir()
            trace = scratch / "trace.jsonl"
            docker = DockerExecutor(workspace)
            self.assertEqual(trace.resolve().as_posix(), docker.visible_path(trace))


@unittest.skipUnless(image_present(DEFAULT_IMAGE), f"本地没有 {DEFAULT_IMAGE}，跳过")
class DockerRunTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(support.isolated_runs_dir())

    def test_command_runs_in_container(self):
        with support.scratch_dir() as ws:
            result = DockerExecutor(ws).run(
                ["python", "-c", "import sys,platform;"
                 "print(platform.python_version());print(sys.platform)"],
                ws, 120.0)
            self.assertEqual("", result.launcher_error)
            self.assertEqual(0, result.exit_code)
            self.assertTrue(result.stdout.startswith("3."), result.stdout)

    def test_bind_mount_is_shared_both_ways(self):
        with support.scratch_dir() as ws:
            (ws / "host_side.txt").write_text("written on host\n",
                                              encoding="utf-8", newline="\n")
            ex = DockerExecutor(ws)
            read = ex.run(["python", "-c", "print(open('host_side.txt').read().strip())"],
                          ws, 120.0)
            self.assertEqual(0, read.exit_code)
            self.assertIn("written on host", read.stdout)

            ex.run(["python", "-c",
                    "open('container_side.txt','w').write('written in container')"],
                   ws, 120.0)
            self.assertEqual("written in container",
                             (ws / "container_side.txt").read_text(encoding="utf-8"))

    def test_run_dir_around_workspace_is_not_mounted(self):
        # 隔离面的机械断言。run_dir 里放着 trace.jsonl / meta.json，
        # 若把它们挂进去，被观测的 agent 就能改掉观察它自己的证据。
        with support.scratch_dir() as scratch:
            workspace = scratch / "workspace"
            workspace.mkdir()
            (scratch / "trace.jsonl").write_text("{}\n", encoding="utf-8", newline="\n")
            result = DockerExecutor(workspace).run(
                ["python", "-c", "open('../trace.jsonl').read()"], workspace, 120.0)
            self.assertNotEqual(0, result.exit_code)
            self.assertIn("No such file", result.stderr)

    def test_timeout_leaves_no_container_behind(self):
        # --rm 只在 docker run 正常退出时生效；客户端被 kill 后容器会留下，故显式删。
        with support.scratch_dir() as ws:
            ex = DockerExecutor(ws)
            result = ex.run(["python", "-c", "import time; time.sleep(30)"], ws, 2.0)
            self.assertTrue(result.timed_out)
            self.assertIsNone(result.exit_code)
            leftovers = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name=harness-{os.getpid()}-",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=60, shell=False)
            self.assertEqual("", leftovers.stdout.strip(), leftovers.stdout)


@unittest.skipUnless(image_present(DEFAULT_IMAGE), f"本地没有 {DEFAULT_IMAGE}，跳过")
class DockerControlMatrixTest(unittest.TestCase):
    """换后端后，八个对照组仍必须命中同一批标签。

    这是"后端可替换"的真正断言：标签是主循环算的，不该受执行器影响。
    """

    def setUp(self):
        self.enterContext(support.isolated_runs_dir())

    def test_every_control_hits_its_designed_label_under_docker(self):
        for task_id, agent_name, variant, expected in CONTROLS:
            with self.subTest(task=task_id, agent=agent_name, variant=variant or "repo"):
                task = load_task(task_id)
                failure_class, run_dir = support.run_scenario(
                    ScriptedAgent(agent_name), task,
                    config=docker_config(), variant=variant)
                self.assertEqual(expected, failure_class)
                self.assertEqual([], validate_records(read_trace(run_dir / "trace.jsonl")))

    def test_trace_records_container_paths(self):
        task = load_task("toy-001")
        _, run_dir = support.run_scenario(
            ScriptedAgent("scripted_ok"), task, config=docker_config())
        records = read_trace(run_dir / "trace.jsonl")
        calls = [r for r in records if r["type"] == "tool_call"]
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual("/workspace", call["cwd"])
        verifications = [r for r in records if r["type"] == "verification"]
        self.assertEqual(1, len(verifications))
        self.assertEqual("/workspace", verifications[0]["cwd"])
        self.assertEqual("passed", verifications[0]["status"])
        # 若 {python} 仍解析成宿主 venv 的绝对路径，容器里这个文件不存在，
        # 验证会以 launcher_error 收场而不是 passed。这条钉的就是那件事。
        self.assertEqual("python", verifications[0]["command"][0])
