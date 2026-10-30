import gradio as gr

from novel_system import NovelWorkflow


CSS = """
html, body {height: 100%; overflow: hidden;}
.gradio-container {
    height: 100vh !important;
    max-width: none !important;
    overflow: hidden;
    padding: 12px 18px !important;
    background: linear-gradient(135deg, #f7f4ee 0%, #edf2f6 100%);
}
.hero {height: 72px; overflow: hidden; text-align: center; margin: 0 0 8px;}
.hero h1 {margin: 0; font-size: 26px;}
.hero p {margin: 4px 0 0; color: #5d6873;}
.workspace {height: calc(100vh - 104px); overflow: hidden; gap: 14px;}
.left-panel, .right-panel {
    height: 100%;
    min-height: 0;
    overflow-y: auto;
    padding: 14px;
    border: 1px solid rgba(84, 96, 110, .16);
    border-radius: 16px;
    background: rgba(255, 255, 255, .82);
    box-shadow: 0 8px 30px rgba(40, 50, 60, .08);
}
.status-bar {
    min-height: 42px;
    padding: 9px 12px;
    border-radius: 10px;
    background: #eef6ff;
    border-left: 4px solid #3978b8;
}
.manuscript {
    height: calc(100vh - 300px);
    min-height: 180px;
    overflow-y: auto !important;
    padding: 18px 22px;
    border-radius: 12px;
    background: #fffefb;
    line-height: 1.85;
    white-space: pre-wrap;
}
.right-panel {overflow: hidden;}
.output-tabs {min-height: 0; overflow: hidden;}
.review-reader {height: calc(100vh - 300px); min-height: 180px; overflow-y: auto !important;}
.action-row {position: sticky; bottom: 0; background: white; padding-top: 8px; z-index: 2;}
@media (max-width: 900px) {
    html, body, .gradio-container {height: auto !important; overflow: auto;}
    .workspace {height: auto; overflow: visible;}
    .left-panel, .right-panel {height: auto; max-height: none;}
}
"""


def _workflow(value):
    return value if isinstance(value, NovelWorkflow) else NovelWorkflow()


def _list_markdown(items, empty_text):
    return "\n".join(f"- {item}" for item in items) or empty_text


def _collaboration_messages(messages):
    return [{
        "role": "user" if item["agent"] in ("独立审稿 Agent", "协调器") else "assistant",
        "content": f"**{item['agent']} → {item.get('recipient', '协作团队')}** · {item.get('kind', 'message')}\n\n{item['message'] or '正在组织消息…'}",
    } for item in messages]


def _view(workflow):
    state = workflow.state
    return (
        workflow,
        f"**当前状态：** {state.status}",
        state.story_bible,
        state.outline,
        state.plan,
        state.memory,
        _list_markdown(state.facts, "尚无事实记录。"),
        _list_markdown(state.open_threads, "尚无未决线索。"),
        state.review or "尚未生成正文。",
        state.manuscript,
        _collaboration_messages(state.collaboration),
    )


def generate_outline(workflow, idea, requirements):
    workflow = _workflow(workflow)
    for _ in workflow.stream_outline(idea, requirements):
        yield _view(workflow)


def generate_opening(workflow, style):
    workflow = _workflow(workflow)
    for _ in workflow.stream_opening(style):
        yield _view(workflow)


def generate_next(workflow, style):
    workflow = _workflow(workflow)
    for _ in workflow.stream_continue(style):
        yield _view(workflow)


def build_app():
    with gr.Blocks(title="多 Agent 小说创作系统") as demo:
        workflow = gr.State(None)
        gr.Markdown(
            "# 多 Agent 小说创作系统\n"
            "自主查阅历史 · 编辑与作者多轮协作 · 实时对话 · 故事记忆",
            elem_classes="hero",
        )

        with gr.Row(equal_height=True, elem_classes="workspace"):
            with gr.Column(scale=4, elem_classes="left-panel"):
                with gr.Tabs():
                    with gr.Tab("创作控制台"):
                        idea = gr.Textbox(
                            label="小说创意",
                            placeholder="主角是谁？他想要什么？什么阻止了他？",
                            lines=4,
                        )
                        requirements = gr.Textbox(
                            label="创作约束",
                            placeholder="题材、受众、人物限制、需要避开的内容",
                            lines=3,
                        )
                        style = gr.Textbox(
                            label="文风要求",
                            placeholder="例如：第三人称限知，节奏紧凑，对话克制",
                            lines=3,
                        )
                        with gr.Row(elem_classes="action-row"):
                            outline_button = gr.Button("① 生成大纲", variant="primary")
                            opening_button = gr.Button("② 创作开篇")
                            next_button = gr.Button("③ 继续下一幕")
                    with gr.Tab("故事圣经"):
                        story_bible = gr.Textbox(label="长期设定", lines=18, interactive=False)
                    with gr.Tab("剧情蓝图"):
                        outline = gr.Textbox(label="阶段大纲", lines=15, interactive=False)
                        plan = gr.Textbox(label="当前任务", lines=4, interactive=False)
                    with gr.Tab("记忆与线索"):
                        memory = gr.Textbox(label="长期记忆", lines=9, interactive=False)
                        facts = gr.Markdown("尚无事实记录。")
                        threads = gr.Markdown("尚无未决线索。")

            with gr.Column(scale=6, elem_classes="right-panel"):
                status = gr.Markdown("**当前状态：** 等待操作", elem_classes="status-bar")
                with gr.Tabs(elem_classes="output-tabs"):
                    with gr.Tab("小说正文"):
                        manuscript = gr.Markdown("正文将在这里流式显示。", elem_classes="manuscript")
                    with gr.Tab("Agent 对话"):
                        collaboration = gr.Chatbot(label="Agent 协作现场", height="calc(100vh - 300px)")
                    with gr.Tab("本轮审稿"):
                        review = gr.Markdown("尚未生成正文。", elem_classes="review-reader")

        outputs = [
            workflow,
            status,
            story_bible,
            outline,
            plan,
            memory,
            facts,
            threads,
            review,
            manuscript,
            collaboration,
        ]
        outline_button.click(
            generate_outline,
            inputs=[workflow, idea, requirements],
            outputs=outputs,
            concurrency_id="story_workflow",
        )
        opening_button.click(generate_opening, inputs=[workflow, style], outputs=outputs, concurrency_id="story_workflow")
        next_button.click(generate_next, inputs=[workflow, style], outputs=outputs, concurrency_id="story_workflow")
    return demo


demo = build_app()


if __name__ == "__main__":
    demo.queue().launch(css=CSS)
