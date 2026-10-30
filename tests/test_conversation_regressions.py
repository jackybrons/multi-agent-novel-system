import json
import unittest
from app import _view
from novel_system import NovelWorkflow
from tests.test_collaboration import CollaborationGateway
from tests.test_agent_loop import DecisionGateway


class CharacterGateway(CollaborationGateway):
    def stream_json(self, name, prompt, payload):
        yield from json.dumps(self.generate(name, prompt, payload), ensure_ascii=False)


class ConversationRegressionTest(unittest.TestCase):
    def test_review_limit_hands_off_to_final_editor(self):
        gateway = DecisionGateway('revise')
        workflow = NovelWorkflow(gateway)
        workflow.create_outline('怀表')
        events = list(workflow.stream_opening())
        self.assertEqual(events[-1].phase, 'memory_done')
        self.assertEqual(workflow.state.chapters, ['最终场景'])
        payload = next(p for name, p in gateway.calls if name == '修订 Agent')
        self.assertFalse(payload['review_approved'])
        self.assertEqual(payload['critic_review']['conflicts'], ['动机不足'])

    def test_streaming_content_is_visible_in_chat_before_completion(self):
        workflow = NovelWorkflow(CharacterGateway())
        workflow.create_outline('怀表')
        snapshots = {phase: [] for phase in ('draft_delta', 'writer_response_delta', 'memory_delta')}
        for event in workflow.stream_opening():
            if event.phase in snapshots:
                snapshots[event.phase].append(_view(workflow)[-1][-1]['content'])
        for phase, text in [('draft_delta', '第一版场'), ('writer_response_delta', '补足动机后的场'), ('memory_delta', '主角因冒险丢失怀表')]:
            with self.subTest(phase=phase):
                self.assertTrue(any(text in content for content in snapshots[phase]), f'{phase} 未显示流式内容')


if __name__ == '__main__':
    unittest.main()
