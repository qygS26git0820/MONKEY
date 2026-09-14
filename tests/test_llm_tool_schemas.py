"""每个注册工具必须恰好有一条 schema，反之亦然。

`tools/base.py` 是冻结的，`Tool` 只有 `name` 与 `execute`，没有 schema。于是
"加了工具却忘了写 schema"会是一个**静默**故障：那个工具对模型不存在，而所有
测试照旧绿。这条测试就是那条漂移的机械拦截（审计 §7.3）。
"""

import unittest

from harness.llm import prompt
from harness.tools.registry import ToolRegistry


class ToolSchemaDriftTest(unittest.TestCase):
    def setUp(self):
        self.registry_names = sorted(ToolRegistry().names())
        self.schema_names = sorted(s["function"]["name"] for s in prompt.TOOL_SCHEMAS)

    def test_registered_tools_and_schemas_are_the_same_set(self):
        self.assertEqual(self.registry_names, self.schema_names,
                         "注册工具与 schema 的名字集合不一致")

    def test_schema_names_are_unique(self):
        names = [s["function"]["name"] for s in prompt.TOOL_SCHEMAS]
        self.assertEqual(len(names), len(set(names)))

    def test_each_schema_is_a_well_formed_function_description(self):
        for schema in prompt.TOOL_SCHEMAS:
            with self.subTest(tool=schema["function"]["name"]):
                self.assertEqual("function", schema["type"])
                function = schema["function"]
                self.assertTrue(function["description"])
                params = function["parameters"]
                self.assertEqual("object", params["type"])
                # required 若不是 properties 的子集，模型永远凑不出一次合法调用。
                self.assertTrue(set(params["required"]) <= set(params["properties"]))

    def test_run_verify_declares_no_arguments(self):
        schema = next(s for s in prompt.TOOL_SCHEMAS
                      if s["function"]["name"] == "run_verify")
        params = schema["function"]["parameters"]
        self.assertEqual({}, params["properties"])
        self.assertEqual([], params["required"])


class SystemPromptTest(unittest.TestCase):
    class _State:
        workspace = "/tmp/ws-marker-9f3"
        description = "修好 calc.py"

    def test_the_prompt_names_every_registered_tool(self):
        text = prompt.system_prompt(self._State())

        for name in ToolRegistry().names():
            with self.subTest(tool=name):
                self.assertIn(name, text)

    def test_the_workspace_is_substituted_not_left_as_a_placeholder(self):
        text = prompt.system_prompt(self._State())

        self.assertIn(self._State.workspace, text)
        self.assertNotIn("<<WORKSPACE>>", text)

    def test_a_workspace_path_with_braces_renders_verbatim(self):
        # 用 <<标记>> 替换而不是 str.format 的理由：路径里出现花括号时 format
        # 会抛错，而提示词最不该被这类意外绊住。
        class Weird:
            workspace = "/tmp/{odd}/ws"
            description = "x"

        self.assertIn("/tmp/{odd}/ws", prompt.system_prompt(Weird()))
