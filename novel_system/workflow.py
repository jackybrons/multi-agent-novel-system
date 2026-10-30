import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol

from .llm import DeepSeekGateway
from .prompts import (
    CRITIC_PROMPT,
    RESEARCH_PROMPT,
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
        self.researcher = Agent("资料检索 Agent", RESEARCH_PROMPT, ("action", "reason", "arguments"), gateway)
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
            ("questions", "conflicts", "strengths", "revision_goals", "decision"),
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
        for _ in self.stream_outline(idea, requirements):
            pass
        return self.state

    def stream_outline(self, idea: str, requirements: str = "") -> Iterator[WorkflowEvent]:
        if not idea.strip():
            raise ValueError("请先输入小说创意。")
        self.state = StoryState(
            idea=idea.strip(),
            requirements=requirements.strip(),
            status="故事策划 Agent 正在流式建立故事蓝图…",
        )
        self._record("故事策划 Agent", "正在建立故事蓝图…", "正文写作 Agent", "handoff")
        yield self._event("outline_start", self.state.status)
        buffer = ""
        for delta in self.planner.stream_json({"idea": idea, "requirements": requirements}):
            buffer += delta
            self.state.story_bible = self._extract_partial_json_string(buffer, "story_bible")
            self.state.outline = self._extract_partial_json_string(buffer, "outline")
            self.state.plan = self._extract_partial_json_string(buffer, "next_mission")
            self.state.handoff = self._extract_partial_json_array_strings(buffer, "handoff")
            self.state.collaboration[-1]["message"] = f"**故事设定**\n{self.state.story_bible}\n\n**大纲**\n{self.state.outline}\n\n**下一幕**\n{self.state.plan}"
            yield self._event("outline_delta", "故事策划 Agent 正在流式建立故事蓝图…")
        result = self.planner.validate(self._load_streamed_json(buffer, self.planner.name))
        self.state.story_bible = str(result["story_bible"])
        self.state.outline = str(result["outline"])
        self.state.plan = str(result["next_mission"])
        self.state.handoff = [str(item) for item in result["handoff"]]
        self._record(
            "故事策划 Agent",
            f"已建立故事圣经。下一幕任务：{self.state.plan}\n"
            f"交接事项：{'；'.join(self.state.handoff)}",
        )
        yield self._event("outline_done", "故事蓝图已生成，可以开始创作开篇")

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
        self.state.preview_text = ""
        try:
            yield from self._run_round(mode, style)
        except Exception as exc:
            self.state.preview_text = ""
            self._record("协调器", f"本轮未提交：{exc}", "用户", "error")
            yield self._event("error", f"本轮未提交：{exc}")
            raise

    def _retrieve(self) -> Iterator[WorkflowEvent]:
        observations = []
        for step in range(3):
            self._record("资料检索 Agent", "正在选择查询方式…", "故事工具", "tool_call")
            yield self._event("research_start", "资料检索 Agent 正在选择查询方式…")
            action_buffer = ""
            payload = {
                "mission": self.state.plan, "memory": self.state.memory,
                "chapter_count": len(self.state.chapters), "observations": observations,
            }
            for delta in self.researcher.stream_json(payload):
                action_buffer += delta
                self.state.collaboration[-1]["message"] = self._extract_partial_json_string(action_buffer, "reason") or "正在选择查询方式…"
                yield self._event("research_delta", "资料检索 Agent 正在组织查询…")
            action = self.researcher.validate(self._load_streamed_json(action_buffer, self.researcher.name))
            name, args = action["action"], action["arguments"]
            self._record("资料检索 Agent", action["reason"], name, "tool_call")
            yield self._event("tool_call", f"资料检索 Agent：{name}")
            if name == "finish":
                break
            if name == "search_story":
                query = str(args["query"]).strip()
                if not query:
                    raise ValueError("检索词不能为空")
                matches = []
                for index, chapter in enumerate(self.state.chapters):
                    position = chapter.casefold().find(query.casefold())
                    if position >= 0:
                        matches.append({"chapter": index + 1, "excerpt": chapter[max(0, position-100):position+400]})
                result = matches[-5:]
            elif name == "read_chapter":
                index = int(args["chapter"])
                if not 1 <= index <= len(self.state.chapters):
                    raise ValueError("章节编号不存在")
                result = {"chapter": index, "text": self.state.chapters[index-1]}
            else:
                raise ValueError(f"未知故事工具：{name}")
            observations.append({"tool": name, "arguments": args, "result": result})
            self._record(name, json.dumps(result, ensure_ascii=False), "资料检索 Agent", "tool_result")
            yield self._event("tool_result", "历史正文查询完成")
        self._record("资料检索 Agent", f"已交接 {len(observations)} 条工具查询结果。", "正文写作 Agent", "handoff")
        return observations

    def _run_round(self, mode: str, style: str) -> Iterator[WorkflowEvent]:
        if not self.state.outline:
            raise ValueError("请先生成大纲。")

        evidence = (yield from self._retrieve()) if self.state.chapters else []
        recent_text = "\n\n".join(self.state.chapters[-2:])
        shared_context = {
            "evidence": evidence,
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

        self._record("正文写作 Agent", "正在构思场景…", "独立审稿 Agent", "draft")
        yield self._event("draft_start", "正文写作 Agent 正在流式生成初稿…")
        draft_buffer = ""
        displayed_draft = ""
        for delta in self.drafter.stream_json(shared_context):
            draft_buffer += delta
            partial_draft = self._extract_partial_json_string(draft_buffer, "draft")
            intent = self._extract_partial_json_string(draft_buffer, "intent")
            self.state.collaboration[-1]["message"] = f"**创作意图**\n{intent}\n\n**草稿**\n{partial_draft}"
            if partial_draft != displayed_draft:
                displayed_draft = partial_draft
                self.state.preview_text = displayed_draft
                yield self._event("draft_delta", "正文写作 Agent 正在流式生成初稿…")
        try:
            draft = self.drafter.validate(json.loads(draft_buffer))
        except json.JSONDecodeError as exc:
            raise ValueError("正文写作 Agent 的流式 JSON 不完整。") from exc
        self.state.preview_text = str(draft["draft"])
        self.state.collaboration[-1]["message"] = f"创作意图：{draft['intent']}\n\n{draft['draft']}"
        yield self._event("draft_done", "草稿完成，正在交给独立审稿 Agent…")

        original_draft = draft["draft"]
        exchanges = []
        writer_response = {}
        review_approved = False
        for review_round in range(1, 4):
            self._record("协调器", f"第 {review_round}/3 轮审稿，请判断是否可交付。", "独立审稿 Agent", "route")
            yield self._event("critic_start", f"第 {review_round}/3 轮审稿…")
            critic_buffer = ""
            self._record("独立审稿 Agent", "", "写作回应 Agent", "review")
            for delta in self.critic.stream_json({
                **shared_context, "writer_intent": draft["intent"],
                "draft": draft["draft"], "exchanges": exchanges,
            }):
                critic_buffer += delta
                partial = {key: self._extract_partial_json_array_strings(critic_buffer, key)
                           for key in ("questions", "conflicts", "strengths", "revision_goals")}
                self.state.review = self._format_review(partial)
                self.state.collaboration[-1]["message"] = self.state.review
                yield self._event("critic_delta", f"第 {review_round}/3 轮审稿…")
            critic_review = self.critic.validate(self._load_streamed_json(critic_buffer, self.critic.name))
            decision = critic_review["decision"]
            if decision not in ("approve", "revise"):
                raise ValueError("审稿 decision 必须是 approve 或 revise")
            self.state.review = self._format_review(critic_review)
            self.state.collaboration[-1]["message"] = self.state.review + f"\n\n决定：{decision}"
            yield self._event("critic_done", f"审稿决定：{decision}")
            if decision == "approve" and not critic_review["conflicts"]:
                review_approved = True
                self._record("协调器", "审稿通过，交给修订 Agent 完成最终表达。", "修订 Agent", "route")
                break
            if review_round == 3:
                self._record("协调器", "三轮审稿尚未达成一致。将最新稿件、未解决意见和作者回应交给修订 Agent 做最终裁决；不标记为审稿通过。", "修订 Agent", "route")
                yield self._event("review_escalated", "审稿尚未通过，正在交给修订 Agent 处理剩余问题…")
                break
            self._record("写作回应 Agent", "", "独立审稿 Agent", "response")
            yield self._event("writer_response_start", "作者正在回应编辑质询…")
            response_buffer = ""
            for delta in self.writer_response.stream_json({
                **shared_context, "draft": draft["draft"], "critic_review": critic_review,
                "exchanges": exchanges,
            }):
                response_buffer += delta
                sections = []
                for key, title in (("answers", "回答"), ("accepted_changes", "接受"), ("rejected_changes", "拒绝及依据")):
                    items = self._extract_partial_json_array_strings(response_buffer, key)
                    sections.append(f"**{title}**\n" + "\n".join(f"- {item}" for item in items))
                partial_revision = self._extract_partial_json_string(response_buffer, "revised_draft")
                if partial_revision:
                    self.state.preview_text = partial_revision
                    sections.append(f"**修改稿**\n{partial_revision}")
                self.state.collaboration[-1]["message"] = "\n\n".join(sections)
                yield self._event("writer_response_delta", "作者正在回应编辑质询…")
            writer_response = self.writer_response.validate(self._load_streamed_json(response_buffer, self.writer_response.name))
            exchanges.append({"review": critic_review, "response": writer_response})
            draft["draft"] = writer_response["revised_draft"]
            self.state.preview_text = draft["draft"]
            yield self._event("writer_response_done", "修改稿已提交，返回审稿 Agent 复核")

        revision_payload = {
            **shared_context,
            "review_approved": review_approved,
            "original_draft": original_draft,
            "current_draft": draft["draft"],
            "exchanges": exchanges,
            "critic_review": critic_review,
            "writer_response": writer_response,
            "next_plan": draft["next_plan"],
        }
        self.state.preview_text = ""
        yield self._event("revision_start", "修订 Agent 正在输出最终正文…")
        self._record("修订 Agent", "", "故事记忆 Agent", "final")
        for delta in self.reviser.stream(revision_payload):
            self.state.preview_text += delta
            self.state.collaboration[-1]["message"] = self.state.preview_text
            yield self._event("revision_delta", "修订 Agent 正在流式输出正文…")

        final_text = self.state.preview_text.strip()
        if not final_text:
            raise ValueError("修订 Agent 返回了空正文。")
        self._record("修订 Agent", "已综合审稿意见与写作回应，完成最终正文。")
        yield self._event("revision_done", "正文完成，正在更新长期记忆…")

        self._record("故事记忆 Agent", "正在整理本轮事实…", "协作团队", "memory")
        yield self._event("memory_start", "故事记忆 Agent 正在回写事实与未决线索…")
        memory_payload = {
                "story_bible": self.state.story_bible,
                "previous_memory": self.state.memory,
                "previous_facts": self.state.facts,
                "previous_open_threads": self.state.open_threads,
                "candidate_new_facts": draft["new_facts"],
                "final_text": final_text,
        }
        memory_buffer = ""
        for delta in self.memory.stream_json(memory_payload):
            memory_buffer += delta
            summary = self._extract_partial_json_string(memory_buffer, "memory")
            facts = self._extract_partial_json_array_strings(memory_buffer, "facts")
            threads = self._extract_partial_json_array_strings(memory_buffer, "open_threads")
            self.state.collaboration[-1]["message"] = f"**剧情摘要**\n{summary}\n\n**事实**\n" + "\n".join(f"- {x}" for x in facts) + "\n\n**未决线索**\n" + "\n".join(f"- {x}" for x in threads)
            yield self._event("memory_delta", "故事记忆 Agent 正在流式回写事实与未决线索…")
        memory = self.memory.validate(self._load_streamed_json(memory_buffer, self.memory.name))
        updated_memory = str(memory["memory"])
        updated_facts = [str(item) for item in memory["facts"]]
        updated_threads = [str(item) for item in memory["open_threads"]]
        self.state.preview_text = ""
        self.state.chapters.append(final_text)
        self.state.plan = str(draft["next_plan"])
        self.state.handoff = [self.state.plan]
        self.state.memory = updated_memory
        self.state.facts = updated_facts
        self.state.open_threads = updated_threads
        self._record("故事记忆 Agent", "已将最终正文回写为共享记忆、事实和未决线索。")
        yield self._event("memory_done", "本轮创作完成" if review_approved else "本轮创作完成（由修订 Agent 裁决，未获审稿通过；请查看本轮审稿）")

    def _event(self, phase: str, message: str) -> WorkflowEvent:
        self.state.status = message
        return WorkflowEvent(phase, message, self.state.manuscript)

    def _record(self, agent: str, message: str, recipient: str = "协作团队", kind: str = "message") -> None:
        self.state.collaboration.append({
            "agent": agent, "message": message, "recipient": recipient,
            "kind": kind, "scene": str(len(self.state.chapters) + 1),
        })

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

    @classmethod
    def _extract_partial_json_array_strings(cls, buffer: str, key: str) -> list[str]:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*\[', buffer)
        if not match:
            return []
        raw = buffer[match.end() :]
        in_string = False
        escaped = False
        end = len(raw)
        for index, char in enumerate(raw):
            if escaped:
                escaped = False
            elif char == "\\" and in_string:
                escaped = True
            elif char == '"':
                in_string = not in_string
            elif char == "]" and not in_string:
                end = index
                break
        raw = raw[:end]
        items = []
        for item_match in re.finditer(r'"((?:\\.|[^"\\])*)(?:"|$)', raw):
            encoded = item_match.group(1)
            try:
                items.append(json.loads(f'"{encoded}"'))
            except json.JSONDecodeError:
                items.append(cls._extract_partial_json_string(f'"value":"{encoded}', "value"))
        return items

    @staticmethod
    def _load_streamed_json(buffer: str, agent_name: str) -> dict[str, Any]:
        try:
            return json.loads(buffer)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{agent_name} 的流式 JSON 不完整。") from exc

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
