"""OpenAI-compatible intent adapter with strict validation and bounded retry."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from loreal_ai_service_intelligence.domain.models import (
    ConversationRequest,
    ConversationState,
    EmpathyCard,
    IntentResult,
    StoredConversation,
)

Transport = Callable[[Request, float], bytes]


class OpenAICompatibleIntentProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        retry_limit: int,
        transport: Transport | None = None,
    ) -> None:
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required when LLM is enabled")
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retry_limit = retry_limit
        self.transport = transport or self._send

    def classify(self, text: str) -> IntentResult:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify the user's beauty-service intent. Return JSON only with "
                        "intent and confidence. intent must be one of consult, purchase, usage, "
                        "after_sales, complaint, other. confidence must be between 0 and 1."
                    ),
                },
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw = self._request_with_retry(request)
        body: dict[str, Any] = json.loads(raw)
        content = body["choices"][0]["message"]["content"]
        result = json.loads(content) if isinstance(content, str) else content
        result["source"] = f"openai_compatible:{self.model}"[:100]
        return IntentResult.model_validate(result)

    def generate(
        self,
        request: ConversationRequest,
        card: EmpathyCard,
        existing: StoredConversation | None,
    ) -> str:
        """基于上下文生成话术，但不允许模型修改上游决策。"""
        history = []
        if existing:
            history = [
                {"role": item.role, "content": item.content} for item in existing.transcript[-8:]
            ]
        evidence = [ref.excerpt for ref in card.knowledge_refs]
        constraints = {
            ConversationState.ASK: "只追问一个最关键的问题，不给未经证实的结论。",
            ConversationState.GUIDE: "只给一个可执行步骤，说明观察目标；只能使用提供的审核依据。",
            ConversationState.RESOLVE: "直接回答用户当前问题；只能使用提供的审核依据。",
            ConversationState.HANDOFF: "说明转人工原因，并告知历史对话会同步，不继续猜测答案。",
            ConversationState.BLOCK: "明确建议停止相关操作并寻求专业帮助，不诊断、不推荐产品。",
        }
        context = {
            "fixed_state": card.next_state.value,
            "intent": card.intent.value,
            "scenario": card.scenario,
            "emotion_signal": card.emotion,
            "known_facts": card.confirmed_facts,
            "missing_information": card.missing_information,
            "approved_evidence": evidence,
            "current_message": request.message,
        }
        payload = {
            "model": self.model,
            "temperature": 0.3,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是美妆品牌在线客服。理解用户真正的问题和当前情绪，结合对话上下文，"
                        "用自然、简洁、不重复的中文回复。上游 fixed_state 已由安全策略确定，绝不能"
                        "改变状态或越过边界。不得编造产品、功效、订单、政策、医学结论或审核依据。"
                        f"当前回复约束：{constraints[card.next_state]}"
                        '仅返回 JSON：{"message": "消费者可见回复"}。'
                    ),
                },
                *history,
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        result = self._completion(payload)
        message = result.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 1200:
            raise ValueError("LLM response message is invalid")
        return message.strip()

    def _completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw = self._request_with_retry(request)
        body: dict[str, Any] = json.loads(raw)
        content = body["choices"][0]["message"]["content"]
        result = json.loads(content) if isinstance(content, str) else content
        if not isinstance(result, dict):
            raise ValueError("LLM response must be a JSON object")
        return result

    def _request_with_retry(self, request: Request) -> bytes:
        for attempt in range(self.retry_limit + 1):
            try:
                return self.transport(request, self.timeout_seconds)
            except (TimeoutError, URLError):
                if attempt >= self.retry_limit:
                    raise
        raise RuntimeError("unreachable retry state")

    @staticmethod
    def _send(request: Request, timeout_seconds: float) -> bytes:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return response.read()
