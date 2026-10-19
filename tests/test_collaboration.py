import unittest

from novel_system import NovelWorkflow


class CollaborationGateway:
    def __init__(self):
        self.calls = []

    def generate(self, agent_name, system_prompt, payload):
        self.calls.append((agent_name, payload))
        responses = {
            "故事策划 Agent": {
                "story_bible": "世界规则与人物弧光",
                "outline": "三幕剧情大纲",
                "next_mission": "用一次失败建立核心冲突",
                "handoff": ["主角必须主动做出错误选择"],
            },
            "正文写作 Agent": {
                "draft": "第一版场景",
                "next_plan": "追查失败原因",
                "new_facts": ["主角丢失怀表"],
                "intent": "让主角为错误选择付出代价",
            },
            "独立审稿 Agent": {
                "questions": ["主角为何冒险？"],
                "conflicts": ["动机没有落到行动"],
                "strengths": ["失败结果明确"],
                "revision_goals": ["补足冒险动机"],
            },
            "写作回应 Agent": {
                "answers": ["他想找回父亲留下的怀表"],
                "accepted_changes": ["在行动前补充选择依据"],
                "rejected_changes": [],
                "revised_draft": "补足动机后的场景",
            },
            "修订 Agent": {"text": "最终场景"},
            "故事记忆 Agent": {
                "memory": "主角因冒险丢失怀表。",
                "facts": ["主角丢失怀表"],
                "open_threads": ["怀表去向"],
            },
        }
        return responses[agent_name]


class CollaborationTest(unittest.TestCase):
    def test_critic_and_writer_exchange_before_revision(self):
        gateway = CollaborationGateway()
        workflow = NovelWorkflow(gateway)
        workflow.create_outline("测试创意")
        workflow.create_opening()

        self.assertEqual(
            [name for name, _ in gateway.calls],
            [
                "故事策划 Agent",
                "正文写作 Agent",
                "独立审稿 Agent",
                "写作回应 Agent",
                "修订 Agent",
                "故事记忆 Agent",
            ],
        )
        reviser_payload = gateway.calls[4][1]
        self.assertIn("writer_response", reviser_payload)
        self.assertIn("critic_review", reviser_payload)
        self.assertGreaterEqual(len(workflow.state.collaboration), 5)

    def test_outline_is_required_before_writing(self):
        workflow = NovelWorkflow(CollaborationGateway())
        with self.assertRaisesRegex(ValueError, "请先生成大纲"):
            workflow.create_opening()


if __name__ == "__main__":
    unittest.main()
