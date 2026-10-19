from dataclasses import dataclass, field
from typing import Any, Protocol

from .llm import DeepSeekGateway
from .prompts import (
    CRITIC_PROMPT,
    DRAFTER_PROMPT,
    MEMORY_PROMPT,
    PLANNER_PROMPT,
    REVISER_PROMPT,
)


class Gateway(Protocol):
    def generate(
        self, agent_name: str, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass
class StoryState:
    idea: str = ""
    requirements: str = ""
    outline: str = ""
    plan: str = ""
    memory: str = ""
    facts: list[str] = field(default_factory=list)
    chapters: list[str] = field(default_factory=list)
    review: str = ""
    trace: list[str] = field(default_factory=list)

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
    """以共享故事状态串联五个职责独立的 Agent。"""

    def __init__(self, gateway: Gateway | None = None):
        gateway = gateway or DeepSeekGateway()
        self.state = StoryState()
        self.planner = Agent(
            "故事策划 Agent", PLANNER_PROMPT, ("outline", "initial_plan"), gateway
        )
        self.drafter = Agent(
            "正文写作 Agent", DRAFTER_PROMPT, ("draft", "next_plan", "new_facts"), gateway
        )
        self.critic = Agent(
            "独立审稿 Agent",
            CRITIC_PROMPT,
            ("issues", "strengths", "revision_instructions"),
            gateway,
        )
        self.reviser = Agent("修订 Agent", REVISER_PROMPT, ("text",), gateway)
        self.memory = Agent("故事记忆 Agent", MEMORY_PROMPT, ("memory", "facts"), gateway)

    def create_outline(self, idea: str, requirements: str = "") -> StoryState:
        if not idea.strip():
            raise ValueError("请先输入小说创意。")
        result = self.planner.run({"idea": idea, "requirements": requirements})
        self.state = StoryState(
            idea=idea.strip(),
            requirements=requirements.strip(),
            outline=str(result["outline"]),
            plan=str(result["initial_plan"]),
            trace=["故事策划 Agent：已生成大纲与开篇计划"],
        )
        return self.state

    def create_opening(self, style: str = "") -> StoryState:
        return self._write_round("opening", style)

    def continue_story(self, style: str = "") -> StoryState:
        return self._write_round("continuation", style)

    def _write_round(self, mode: str, style: str) -> StoryState:
        if not self.state.outline:
            raise ValueError("请先生成大纲。")

        recent_text = "\n\n".join(self.state.chapters[-2:])
        draft = self.drafter.run(
            {
                "mode": mode,
                "idea": self.state.idea,
                "requirements": self.state.requirements,
                "style": style,
                "outline": self.state.outline,
                "plan": self.state.plan,
                "memory": self.state.memory,
                "facts": self.state.facts,
                "recent_text": recent_text,
            }
        )
        self.state.trace.append("正文写作 Agent：已完成场景草稿")

        review = self.critic.run(
            {
                "outline": self.state.outline,
                "plan": self.state.plan,
                "memory": self.state.memory,
                "facts": self.state.facts,
                "recent_text": recent_text,
                "draft": draft["draft"],
            }
        )
        self.state.review = self._format_review(review)
        self.state.trace.append("独立审稿 Agent：已检查一致性与叙事质量")

        revised = self.reviser.run(
            {
                "outline": self.state.outline,
                "memory": self.state.memory,
                "facts": self.state.facts,
                "draft": draft["draft"],
                "review": review,
                "style": style,
            }
        )
        final_text = str(revised["text"]).strip()
        if not final_text:
            raise ValueError("修订 Agent 返回了空正文。")
        self.state.chapters.append(final_text)
        self.state.plan = str(draft["next_plan"])
        self.state.trace.append("修订 Agent：已根据审稿意见交付正文")

        memory = self.memory.run(
            {
                "previous_memory": self.state.memory,
                "previous_facts": self.state.facts,
                "new_facts": draft["new_facts"],
                "latest_text": final_text,
            }
        )
        self.state.memory = str(memory["memory"])
        self.state.facts = [str(item) for item in memory["facts"]]
        self.state.trace.append("故事记忆 Agent：已更新长期记忆与事实清单")
        return self.state

    @staticmethod
    def _format_review(review: dict[str, Any]) -> str:
        sections = []
        for title, key in (
            ("必须修复", "issues"),
            ("应当保留", "strengths"),
            ("修订指令", "revision_instructions"),
        ):
            items = review.get(key) or []
            content = "\n".join(f"- {item}" for item in items) or "- 无"
            sections.append(f"### {title}\n{content}")
        return "\n\n".join(sections)
