from dataclasses import dataclass, field
from typing import Any, Protocol

from .llm import DeepSeekGateway
from .prompts import (
    CRITIC_PROMPT,
    DRAFTER_PROMPT,
    MEMORY_PROMPT,
    PLANNER_PROMPT,
    REVISER_PROMPT,
    WRITER_RESPONSE_PROMPT,
)


class Gateway(Protocol):
    def generate(
        self, agent_name: str, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass
class StoryState:
    idea: str = ""
    requirements: str = ""
    story_bible: str = ""
    outline: str = ""
    plan: str = ""
    handoff: list[str] = field(default_factory=list)
    memory: str = ""
    facts: list[str] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    chapters: list[str] = field(default_factory=list)
    review: str = ""
    collaboration: list[dict[str, str]] = field(default_factory=list)

    @property
    def manuscript(self) -> str:
        return "\n\n".join(self.chapters)


class Agent:
    def __init__(
        self,
        name: str,
        prompt: str,
        required_keys: tuple[str, ...],
        gateway: Gateway,
    ):
        self.name = name
        self.prompt = prompt
        self.required_keys = required_keys
        self.gateway = gateway

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.gateway.generate(self.name, self.prompt, payload)
        missing = [key for key in self.required_keys if key not in result]
        if missing:
            raise ValueError(f"{self.name} 缺少字段：{', '.join(missing)}")
        return result


class NovelWorkflow:
    """通过任务交接、编辑质询和写作回应组织多 Agent 协作。"""

    def __init__(self, gateway: Gateway | None = None):
        gateway = gateway or DeepSeekGateway()
        self.state = StoryState()
        self.planner = Agent(
            "故事策划 Agent",
            PLANNER_PROMPT,
            ("story_bible", "outline", "next_mission", "handoff"),
            gateway,
        )
        self.drafter = Agent(
            "正文写作 Agent",
            DRAFTER_PROMPT,
            ("intent", "draft", "next_plan", "new_facts"),
            gateway,
        )
        self.critic = Agent(
            "独立审稿 Agent",
            CRITIC_PROMPT,
            ("questions", "conflicts", "strengths", "revision_goals"),
            gateway,
        )
        self.writer_response = Agent(
            "写作回应 Agent",
            WRITER_RESPONSE_PROMPT,
            ("answers", "accepted_changes", "rejected_changes", "revised_draft"),
            gateway,
        )
        self.reviser = Agent("修订 Agent", REVISER_PROMPT, ("text",), gateway)
        self.memory = Agent(
            "故事记忆 Agent",
            MEMORY_PROMPT,
            ("memory", "facts", "open_threads"),
            gateway,
        )

    def create_outline(self, idea: str, requirements: str = "") -> StoryState:
        if not idea.strip():
            raise ValueError("请先输入小说创意。")
        result = self.planner.run({"idea": idea, "requirements": requirements})
        self.state = StoryState(
            idea=idea.strip(),
            requirements=requirements.strip(),
            story_bible=str(result["story_bible"]),
            outline=str(result["outline"]),
            plan=str(result["next_mission"]),
            handoff=[str(item) for item in result["handoff"]],
        )
        self._record(
            "故事策划 Agent",
            f"已建立故事圣经。下一幕任务：{self.state.plan}\n"
            f"交接事项：{'；'.join(self.state.handoff)}",
        )
        return self.state

    def create_opening(self, style: str = "") -> StoryState:
        return self._write_round("开篇", style)

    def continue_story(self, style: str = "") -> StoryState:
        return self._write_round("续写", style)

    def _write_round(self, mode: str, style: str) -> StoryState:
        if not self.state.outline:
            raise ValueError("请先生成大纲。")

        recent_text = "\n\n".join(self.state.chapters[-2:])
        shared_context = {
            "mode": mode,
            "idea": self.state.idea,
            "requirements": self.state.requirements,
            "style": style,
            "story_bible": self.state.story_bible,
            "outline": self.state.outline,
            "mission": self.state.plan,
            "handoff": self.state.handoff,
            "memory": self.state.memory,
            "facts": self.state.facts,
            "open_threads": self.state.open_threads,
            "recent_text": recent_text,
        }
        draft = self.drafter.run(shared_context)
        self._record("正文写作 Agent", f"创作意图：{draft['intent']}\n已提交第一版草稿。")

        critic_review = self.critic.run(
            {
                **shared_context,
                "writer_intent": draft["intent"],
                "draft": draft["draft"],
            }
        )
        self.state.review = self._format_review(critic_review)
        self._record(
            "独立审稿 Agent",
            self._format_exchange(critic_review["questions"], critic_review["conflicts"]),
        )

        writer_response = self.writer_response.run(
            {
                **shared_context,
                "draft": draft["draft"],
                "critic_review": critic_review,
            }
        )
        self._record(
            "写作回应 Agent",
            self._format_exchange(
                writer_response["answers"], writer_response["accepted_changes"]
            ),
        )

        revised = self.reviser.run(
            {
                **shared_context,
                "original_draft": draft["draft"],
                "critic_review": critic_review,
                "writer_response": writer_response,
                "next_plan": draft["next_plan"],
            }
        )
        final_text = str(revised["text"]).strip()
        if not final_text:
            raise ValueError("修订 Agent 返回了空正文。")
        self.state.chapters.append(final_text)
        self.state.plan = str(draft["next_plan"])
        self.state.handoff = [self.state.plan]
        self._record("修订 Agent", "已综合审稿意见与写作回应，完成最终正文。")

        memory = self.memory.run(
            {
                "story_bible": self.state.story_bible,
                "previous_memory": self.state.memory,
                "previous_facts": self.state.facts,
                "previous_open_threads": self.state.open_threads,
                "candidate_new_facts": draft["new_facts"],
                "final_text": final_text,
            }
        )
        self.state.memory = str(memory["memory"])
        self.state.facts = [str(item) for item in memory["facts"]]
        self.state.open_threads = [str(item) for item in memory["open_threads"]]
        self._record("故事记忆 Agent", "已将最终正文回写为共享记忆、事实和未决线索。")
        return self.state

    def _record(self, agent: str, message: str) -> None:
        self.state.collaboration.append({"agent": agent, "message": message})

    @staticmethod
    def _format_exchange(primary: list[Any], secondary: list[Any]) -> str:
        items = [str(item) for item in [*primary, *secondary]]
        return "\n".join(f"- {item}" for item in items) or "- 本轮无新增问题"

    @staticmethod
    def _format_review(review: dict[str, Any]) -> str:
        sections = []
        for title, key in (
            ("编辑质询", "questions"),
            ("必须修复", "conflicts"),
            ("应当保留", "strengths"),
            ("修订目标", "revision_goals"),
        ):
            items = review.get(key) or []
            content = "\n".join(f"- {item}" for item in items) or "- 无"
            sections.append(f"### {title}\n{content}")
        return "\n\n".join(sections)
