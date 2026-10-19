import unittest

from novel_system import NovelWorkflow

from tests.test_collaboration import CollaborationGateway


class StreamingGateway(CollaborationGateway):
    def generate(self, agent_name, system_prompt, payload):
        if agent_name == "修订 Agent":
            raise AssertionError("最终正文必须走流式接口")
        return super().generate(agent_name, system_prompt, payload)

    def stream_text(self, agent_name, system_prompt, payload):
        self.calls.append((agent_name, payload))
        yield "最终"
        yield "正文"


class StreamingWorkflowTest(unittest.TestCase):
    def test_writing_emits_progress_and_text_deltas(self):
        workflow = NovelWorkflow(StreamingGateway())
        workflow.create_outline("测试创意")

        events = list(workflow.stream_opening())
        phases = [event.phase for event in events]
        streamed_text = [event.manuscript for event in events if event.phase == "revision_delta"]

        self.assertEqual(phases[0], "draft_start")
        self.assertIn("critic_start", phases)
        self.assertIn("writer_response_start", phases)
        self.assertEqual(streamed_text, ["最终", "最终正文"])
        self.assertEqual(workflow.state.manuscript, "最终正文")


if __name__ == "__main__":
    unittest.main()
