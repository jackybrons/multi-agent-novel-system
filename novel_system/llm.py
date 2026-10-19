import json
import os
from typing import Any

from openai import OpenAI


class DeepSeekGateway:
    """DeepSeek 的轻量适配层，只负责发送请求和解析 JSON。"""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

    def generate(
        self,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY。")

        client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.75,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{agent_name} 未返回有效 JSON：{content}") from exc

    def stream_text(
        self,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
    ):
        """逐 token 返回最终正文，供 Gradio 实时刷新。"""
        if not self.api_key:
            raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY。")

        client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            temperature=0.75,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta

    def stream_json(
        self,
        agent_name: str,
        system_prompt: str,
        payload: dict[str, Any],
    ):
        """流式返回 JSON 文本，让工作流提前展示其中的正文草稿。"""
        if not self.api_key:
            raise RuntimeError("请先设置环境变量 DEEPSEEK_API_KEY。")

        client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.75,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield delta
