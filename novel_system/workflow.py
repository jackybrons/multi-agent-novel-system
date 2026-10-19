import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

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


@dataclass(frozen=True)
class WorkflowEvent:
    phase: str
    message: str
    manuscript: str


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
    preview_text: str = ""
    review: str = ""
    status: str = "等待操作"
    collaboration: list[dict[str, str]] = field(default_factory=list)

    @property
    def manuscript(self) -> str:
        sections = [*self.chapters]
        if self.preview_text:
            sections.append(self.preview_text)
        return "\n\n".join(sections)


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
        return self.validate(result)

    def validate(self, result: dict[str, Any]) -> dict[str, Any]:
        missing = [key for key in self.required_keys if key not in result]
        if missing:
            raise ValueError(f"{self.name} 缺少字段：{', '.join(missing)}")
        return result

    def stream_json(self, payload: dict[str, Any]) -> Iterator[str]:
        stream_method = getattr(self.gateway, "stream_json", None)
        if stream_method is None:
            yield json.dumps(self.run(payload), ensure_ascii=False)
            return
        yield from stream_method(self.name, self.prompt, payload)

    def stream(self, payload: dict[str, Any]) -> Iterator[str]:
        stream_method = getattr(self.gateway, "stream_text", None)
        if stream_method is None:
            result = self.run(payload)
            yield str(result["text"])
            return
        yield from stream_method(self.name, self.prompt, payload)


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
        self.state.status = "故事策划 Agent 正在建立故事蓝图…"
        result = self.planner.run({"idea": idea, "requirements": requirements})
        self.state = StoryState(
            idea=idea.strip(),
            requirements=requirements.strip(),
            story_bible=str(result["story_bible"]),
            outline=str(result["outline"]),
            plan=str(result["next_mission"]),
            handoff=[str(item) for item in result["handoff"]],
            status="故事蓝图已生成，可以开始创作开篇",
        )
        self._record(
            "故事策划 Agent",
            f"已建立故事圣经。下一幕任务：{self.state.plan}\n"
            f"交接事项：{'；'.join(self.state.handoff)}",
        )
        return self.state

    def create_opening(self, style: str = "") -> StoryState:
        for _ in self.stream_opening(style):
            pass
        return self.state

    def continue_story(self, style: str = "") -> StoryState:
        for _ in self.stream_continue(style):
            pass
        return self.state

    def stream_opening(self, style: str = "") -> Iterator[WorkflowEvent]:
        yield from self._stream_round("开篇", style)

    def stream_continue(self, style: str = "") -> Iterator[WorkflowEvent]:
        yield from self._stream_round("续写", style)

    def _stream_round(self, mode: str, style: str) -> Iterator[WorkflowEvent]:
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

        yield self._event("draft_start", "正文写作 Agent 正在流式生成初稿…")
        draft_buffer = ""
        displayed_draft = ""
        for delta in self.drafter.stream_json(shared_context):
            draft_buffer += delta
            partial_draft = self._extract_partial_json_string(draft_buffer, "draft")
            if partial_draft != displayed_draft:
                displayed_draft = partial_draft
                self.state.preview_text = displayed_draft
                yield self._event("draft_delta", "正文写作 Agent 正在流式生成初稿…")
        try:
            draft = self.drafter.validate(json.loads(draft_buffer))
        except json.JSONDecodeError as exc:
            raise ValueError("正文写作 Agent 的流式 JSON 不完整。") from exc
        self.state.preview_text = str(draft["draft"])
        self._record("正文写作 Agent", f"创作意图：{draft['intent']}\n已提交第一版草稿。")
        yield self._event("draft_done", "草稿完成，正在交给独立审稿 Agent…")

        yield self._event("critic_start", "独立审稿 Agent 正在检查逻辑与连续性…")
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
        yield self._event("critic_done", "审稿完成，正在等待写作 Agent 回应…")

        yield self._event("writer_response_start", "写作回应 Agent 正在逐项处理编辑质询…")
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
        yield self._event("writer_response_done", "写作回应完成，开始流式生成最终正文…")

        revision_payload = {
            **shared_context,
            "original_draft": draft["draft"],
            "critic_review": critic_review,
            "writer_response": writer_response,
            "next_plan": draft["next_plan"],
        }
        self.state.preview_text = ""
        yield self._event("revision_start", "修订 Agent 正在输出最终正文…")
        for delta in self.reviser.stream(revision_payload):
            self.state.preview_text += delta
            yield self._event("revision_delta", "修订 Agent 正在流式输出正文…")

        final_text = self.state.preview_text.strip()
        if not final_text:
            raise ValueError("修订 Agent 返回了空正文。")
        self.state.preview_text = ""
        self.state.chapters.append(final_text)
        self.state.plan = str(draft["next_plan"])
        self.state.handoff = [self.state.plan]
        self._record("修订 Agent", "已综合审稿意见与写作回应，完成最终正文。")
        yield self._event("revision_done", "正文完成，正在更新长期记忆…")

        yield self._event("memory_start", "故事记忆 Agent 正在回写事实与未决线索…")
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
        yield self._event("memory_done", "本轮创作完成")

    def _event(self, phase: str, message: str) -> WorkflowEvent:
        self.state.status = message
        return WorkflowEvent(phase, message, self.state.manuscript)

    def _record(self, agent: str, message: str) -> None:
        self.state.collaboration.append({"agent": agent, "message": message})

    @staticmethod
    def _extract_partial_json_string(buffer: str, key: str) -> str:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"', buffer)
        if not match:
            return ""
        raw = buffer[match.end() :]
        output = []
        index = 0
        escapes = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
        while index < len(raw):
            char = raw[index]
            if char == '"':
                break
            if char != "\\":
                output.append(char)
                index += 1
                continue
            if index + 1 >= len(raw):
                break
            escaped = raw[index + 1]
            if escaped == "u":
                code = raw[index + 2 : index + 6]
                if len(code) < 4 or not all(item in "0123456789abcdefABCDEF" for item in code):
                    break
                output.append(chr(int(code, 16)))
                index += 6
                continue
            output.append(escapes.get(escaped, escaped))
            index += 2
        return "".join(output)

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
