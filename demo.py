from novel_system import NovelWorkflow


def main():
    workflow = NovelWorkflow()
    workflow.create_outline(
        "失去记忆的修表师发现，每修好一块旧表就会恢复陌生人的一天。",
        "都市奇幻，主角独自调查真相。",
    )
    workflow.create_opening("克制、悬疑，用细节制造不安感。")
    workflow.continue_story("保持紧凑节奏。")

    with open("novel_record.md", "w", encoding="utf-8") as file:
        file.write(workflow.state.manuscript)
    print("小说已保存到 novel_record.md")


if __name__ == "__main__":
    main()
