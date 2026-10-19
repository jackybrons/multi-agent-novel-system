import unittest

from novel_system import NovelWorkflow


class FakeGateway:
    def __init__(self):
        self.calls = []

    def generate(self, agent_name, system_prompt, payload):
        self.calls.append((agent_name, payload))
        responses = {
            "故事策划 Agent": {
                "outline": "修表师追查记忆来源",
                "initial_plan": "修复第一块旧表并付出代价",
            },
            "正文写作 Agent": {
                "draft": "午夜，停摆的旧表重新走动。",
                "next_plan": "追查旧表的委托人",
                "new_facts": ["旧表会释放陌生人的记忆"],
            },
            "独立审稿 Agent": {
                "issues": ["代价尚不明确"],
                "strengths": ["开场意象清晰"],
                "revision_instructions": ["加入主角短暂失去自身记忆的细节"],
            },
            "修订 Agent": {"text": "午夜，旧表重新走动，他却忘了自己的名字。"},
            "故事记忆 Agent": {
                "memory": "主角修复旧表后短暂失去自己的名字。",
                "facts": ["旧表会释放陌生人的记忆", "修表会让主角失去自身记忆"],
            },
        }
        return responses[agent_name]


class NovelWorkflowTest(unittest.TestCase):
    def test_agents_share_state_and_revise_draft(self):
        gateway = FakeGateway()
        workflow = NovelWorkflow(gateway)

        workflow.create_outline("测试创意")
        workflow.create_opening()

        self.assertEqual(
            [name for name, _ in gateway.calls],
            ["故事策划 Agent", "正文写作 Agent", "独立审稿 Agent", "修订 Agent", "故事记忆 Agent"],
        )
        self.assertIn("忘了自己的名字", workflow.state.manuscript)
        self.assertIn("代价尚不明确", workflow.state.review)
        self.assertEqual(len(workflow.state.facts), 2)

    def test_outline_is_required_before_writing(self):
        workflow = NovelWorkflow(FakeGateway())
        with self.assertRaisesRegex(ValueError, "请先生成大纲"):
            workflow.create_opening()


if __name__ == "__main__":
    unittest.main()
