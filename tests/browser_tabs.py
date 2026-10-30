"""Browser regression: run with python tests/browser_tabs.py (requires playwright)."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from novel_system import NovelWorkflow
from tests.test_collaboration import CollaborationGateway
from playwright.sync_api import sync_playwright

class LongGateway(CollaborationGateway):
    def stream_text(self, name, prompt, payload):
        for _ in range(100):
            time.sleep(0.03)
            yield "修表师看向窗外，雨水顺着玻璃缓缓滑落。\n\n"

    def generate(self, name, prompt, payload):
        result = super().generate(name, prompt, payload)
        if name == '独立审稿 Agent':
            result['questions'] = ['主角的动机是否与前文一致？' * 12] * 15
        if name == '修订 Agent':
            result['text'] = ('修表师看向窗外，雨水顺着玻璃缓缓滑落。\n\n' * 100)
        return result

workflow = NovelWorkflow(LongGateway())
workflow.create_outline('怀表')
app._workflow = lambda value: workflow
ui = app.build_app()
try:
    ui.queue().launch(server_name='127.0.0.1', server_port=7867, prevent_thread_lock=True, quiet=True, css=app.CSS)
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path='C:/Program Files/Google/Chrome/Application/chrome.exe', headless=True)
        page = browser.new_page(viewport={'width': 1366, 'height': 768})
        page.goto('http://127.0.0.1:7867')
        page.get_by_role('button', name='② 创作开篇').click()
        page.get_by_text('当前状态： 修订 Agent 正在流式输出正文', exact=False).wait_for(timeout=20000)
        for i in range(3):
            page.get_by_role('tab', name='本轮审稿', exact=True).click()
            page.mouse.move(1100, 600)
            page.mouse.wheel(0, 1800)
            page.wait_for_timeout(300)
            box = page.get_by_role('tab', name='Agent 对话', exact=True).bounding_box()
            print('chat tab after switching:', box)
            assert box and 0 <= box['y'] <= 730, '切到审稿后对话标签离开可视区'
            page.get_by_role('tab', name='Agent 对话', exact=True).click(timeout=5000)
            assert page.get_by_role('tab', name='Agent 对话', exact=True).get_attribute('aria-selected') == 'true'
        print('PASS: repeated review/chat switching with long manuscript and review')
        browser.close()
finally:
    ui.close()
