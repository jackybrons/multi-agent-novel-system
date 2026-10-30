import unittest
from novel_system import NovelWorkflow
from tests.test_collaboration import CollaborationGateway
from app import _view


class DecisionGateway(CollaborationGateway):
    def __init__(self, decision="approve", fail_memory=False):
        super().__init__()
        self.decision = decision
        self.fail_memory = fail_memory

    def generate(self, agent_name, system_prompt, payload):
        if agent_name == "资料检索 Agent":
            self.calls.append((agent_name, payload))
            actions = [
                {"action": "search_story", "reason": "查找怀表", "arguments": {"query": "怀表"}},
                {"action": "read_chapter", "reason": "核对原文", "arguments": {"chapter": 1}},
                {"action": "finish", "reason": "资料充分", "arguments": {}},
            ]
            return actions[len(payload["observations"])]
        if agent_name == "故事记忆 Agent" and self.fail_memory:
            raise RuntimeError("模拟记忆失败")
        result = super().generate(agent_name, system_prompt, payload)
        if agent_name == "独立审稿 Agent":
            result["decision"] = self.decision
            result["conflicts"] = [] if self.decision == "approve" else ["动机不足"]
        return result


class AgentLoopTest(unittest.TestCase):
    def make_workflow(self, gateway):
        workflow = NovelWorkflow(gateway)
        workflow.create_outline("怀表的秘密")
        return workflow

    def test_approval_skips_writer_response(self):
        gateway = DecisionGateway()
        workflow = self.make_workflow(gateway)
        workflow.create_opening()
        self.assertNotIn("写作回应 Agent", [name for name, _ in gateway.calls])
        self.assertEqual(workflow.state.chapters, ["最终场景"])

    def test_rejection_escalates_at_budget(self):
        gateway = DecisionGateway("revise")
        workflow = self.make_workflow(gateway)
        events = list(workflow.stream_opening())
        self.assertEqual(sum(name == "独立审稿 Agent" for name, _ in gateway.calls), 3)
        self.assertIn("review_escalated", [event.phase for event in events])
        self.assertEqual(events[-1].phase, "memory_done")
        self.assertEqual(workflow.state.chapters, ["最终场景"])
        self.assertEqual(workflow.state.preview_text, "")

    def test_memory_failure_keeps_previous_story(self):
        gateway = DecisionGateway(fail_memory=True)
        workflow = self.make_workflow(gateway)
        workflow.state.memory = "旧记忆"
        workflow.state.facts = ["旧事实"]
        previous_plan = workflow.state.plan
        with self.assertRaisesRegex(RuntimeError, "模拟记忆失败"):
            workflow.create_opening()
        self.assertEqual(workflow.state.chapters, [])
        self.assertEqual(workflow.state.memory, "旧记忆")
        self.assertEqual(workflow.state.facts, ["旧事实"])
        self.assertEqual(workflow.state.plan, previous_plan)
        self.assertEqual(workflow.state.preview_text, "")

    def test_tool_observations_reach_writer_and_chat(self):
        gateway = DecisionGateway()
        workflow = self.make_workflow(gateway)
        workflow.state.chapters = ["主角把怀表藏在阁楼。", "第二幕", "第三幕"]
        workflow.continue_story()
        draft_payload = next(payload for name, payload in gateway.calls if name == "正文写作 Agent")
        self.assertEqual(draft_payload["evidence"][1]["result"]["text"], "主角把怀表藏在阁楼。")
        self.assertNotIn("阁楼", draft_payload["recent_text"])
        chat = _view(workflow)[-1]
        self.assertTrue(any("search_story" in message["content"] for message in chat))
        self.assertTrue(any("阁楼" in message["content"] for message in chat))


if __name__ == "__main__":
    unittest.main()
