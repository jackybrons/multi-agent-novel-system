import gradio as gr

from novel_system import NovelWorkflow


CSS = """
.gradio-container {max-width: 1500px !important; margin: auto;}
.hero {text-align: center; margin: 12px 0 24px;}
.panel {border-radius: 14px;}
"""


def _workflow(value):
    return value if isinstance(value, NovelWorkflow) else NovelWorkflow()


def _view(workflow):
    state = workflow.state
    facts = "\n".join(f"- {item}" for item in state.facts)
    trace = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(state.trace))
    return (
        workflow,
        state.outline,
        state.plan,
        state.memory,
        facts,
        state.review,
        state.manuscript,
        trace,
    )


def generate_outline(workflow, idea, requirements):
    workflow = _workflow(workflow)
    workflow.create_outline(idea, requirements)
    return _view(workflow)


def generate_opening(workflow, style):
    workflow = _workflow(workflow)
    workflow.create_opening(style)
    return _view(workflow)


def generate_next(workflow, style):
    workflow = _workflow(workflow)
    workflow.continue_story(style)
    return _view(workflow)


def build_app():
    with gr.Blocks(title="多 Agent 小说创作系统") as demo:
        workflow = gr.State(None)
        gr.Markdown(
            "# 多 Agent 小说创作系统\n"
            "策划、写作、审稿、修订和记忆五个 Agent 共享故事状态，协作完成长篇创作。",
            elem_classes="hero",
        )

        with gr.Row():
            with gr.Column(scale=4, elem_classes="panel"):
                idea = gr.Textbox(
                    label="小说创意",
                    placeholder="例如：失去记忆的修表师发现，每修好一块旧表就会恢复陌生人的一天。",
                    lines=4,
                )
                requirements = gr.Textbox(
                    label="创作约束",
                    placeholder="题材、主角限制、篇幅倾向等",
                    lines=3,
                )
                style = gr.Textbox(
                    label="文风要求",
                    placeholder="例如：克制、悬疑、少用形容词",
                    lines=2,
                )
                outline_button = gr.Button("生成故事大纲", variant="primary")
                opening_button = gr.Button("创作开篇")
                next_button = gr.Button("继续下一幕")

            with gr.Column(scale=6, elem_classes="panel"):
                manuscript = gr.Textbox(label="小说正文", lines=24, interactive=False)

        with gr.Tabs():
            with gr.Tab("故事蓝图"):
                outline = gr.Textbox(label="大纲", lines=14, interactive=False)
                plan = gr.Textbox(label="下一步计划", lines=4, interactive=False)
            with gr.Tab("审稿意见"):
                review = gr.Markdown("尚未生成正文。")
            with gr.Tab("长期记忆"):
                memory = gr.Textbox(label="故事记忆", lines=8, interactive=False)
                facts = gr.Markdown("尚无事实记录。")
            with gr.Tab("协作轨迹"):
                trace = gr.Markdown("尚未调用 Agent。")

        outputs = [workflow, outline, plan, memory, facts, review, manuscript, trace]
        outline_button.click(
            generate_outline,
            inputs=[workflow, idea, requirements],
            outputs=outputs,
        )
        opening_button.click(generate_opening, inputs=[workflow, style], outputs=outputs)
        next_button.click(generate_next, inputs=[workflow, style], outputs=outputs)

    return demo


demo = build_app()


if __name__ == "__main__":
    demo.queue().launch(css=CSS)
