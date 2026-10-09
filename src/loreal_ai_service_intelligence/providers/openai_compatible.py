"""OpenAI-compatible intent adapter with strict validation and bounded retry."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import httpx

from loreal_ai_service_intelligence.domain.competition import P0ContextSnapshot, P0Decision
from loreal_ai_service_intelligence.domain.models import (
    ConsumerReplyGeneration,
    ConversationRequest,
    ConversationState,
    EmpathyCard,
    IntentResult,
    StoredConversation,
)
from loreal_ai_service_intelligence.providers.customer_service_voice import (
    CUSTOMER_SERVICE_VOICE_PROMPT,
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
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required when LLM is enabled")
        self.api_key = api_key
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.retry_limit = retry_limit
        self._client = client if transport is None else None
        if transport is None and self._client is None:
            self._client = httpx.Client()
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
    ) -> ConsumerReplyGeneration:
        """基于上下文生成话术，但不允许模型修改上游决策。"""
        history = []
        if existing:
            history = [
                {"role": item.role, "content": item.content} for item in existing.transcript[-8:]
            ]
        evidence = [ref.excerpt for ref in card.knowledge_refs]
        suggested_replies = self._suggested_replies(card)
        evidence_required = not (
            card.intent_source.startswith("evidence_free_rules:")
            or card.intent_source == "generic_product_guidance_rules"
        )
        recommendation_knowledge_ids = {
            "KB-LOREAL-CN-HOT-SERUM-001",
            "KB-LOREAL-CN-HOT-MOISTURIZER-001",
            "KB-LOREAL-CN-HOT-MASK-001",
            "KB-LOREAL-CN-LIP-001",
        }
        is_direct_recommendation = bool(
            card.next_state == ConversationState.RESOLVE
            and any(ref.knowledge_id in recommendation_knowledge_ids for ref in card.knowledge_refs)
        )
        constraints = {
            ConversationState.ASK: (
                "只追问一个最关键的问题，不给未经证实的结论。能枚举时优先给出 2–4 个互斥短选项，"
                "并包含“不清楚”或“不确定”；只有商品名、订单号等无法枚举的信息才使用开放问题。"
            ),
            ConversationState.GUIDE: "只给一个可执行步骤，说明观察目标；只能使用提供的审核依据。",
            ConversationState.RESOLVE: "直接回答用户当前问题；只能使用提供的审核依据。",
            ConversationState.HANDOFF: "说明转人工原因，并告知历史对话会同步，不继续猜测答案。",
            ConversationState.BLOCK: "明确建议停止相关操作并寻求专业帮助，不诊断、不推荐产品。",
        }
        response_constraint = constraints[card.next_state]
        if card.intent_source == "generic_product_guidance_rules":
            response_constraint = (
                "具体商品身份无法确认，但仍需回答用户问题。先明确不能确认该 SKU 的具体表现，"
                "再提供不依赖该 SKU 的通用品类判断和一个可执行建议。通用经验不得表述成该商品"
                "的官方结论，不得新增功效承诺、适配保证、成分或配方事实，也不要转人工。"
            )
        elif not evidence_required:
            response_constraint = (
                "这是无需业务 evidence 的低风险对话行为。只回应当前寒暄、致谢、确认、告别、"
                "能力询问、问题描述帮助或对上一轮话术的解释；可以使用对话中已有内容进行复述，"
                "但不得新增产品、功效、订单、物流、售后、政策或健康事实。"
            )
        elif is_direct_recommendation:
            response_constraint = (
                "用户已经给出了可用于匹配的需求条件。必须结合 current_message、known_facts 和"
                "对话历史，从 approved_evidence 中选择与这些条件直接匹配的一个主推荐，并说明"
                "匹配的是哪个用户条件和哪条依据；不得固定推荐 evidence 中排在第一的候选。"
                "不能反问偏好，也不能追加开放问题。明确区分官网展示、热门搜索与销量排名，"
                "不扩展任何未提供的功效、肤色适配或使用感承诺。"
            )
        context = {
            "fixed_state": card.next_state.value,
            "intent": card.intent.value,
            "scenario": card.scenario,
            "emotion_signal": card.emotion,
            "known_facts": card.confirmed_facts,
            "missing_information": card.missing_information,
            "approved_evidence": evidence,
            "business_evidence_required": evidence_required,
            "current_message": request.message,
            "allowed_suggested_replies": suggested_replies,
            "available_evidence_media": [
                {
                    "knowledge_id": ref.knowledge_id,
                    "description": ref.image_alt,
                    "review_status": ref.media_review_status,
                }
                for ref in card.knowledge_refs
                if ref.image_url
            ],
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
                        f"当前回复约束：{response_constraint}"
                        f"\n{CUSTOMER_SERVICE_VOICE_PROMPT}"
                        "如果 allowed_suggested_replies 非空，结尾只能逐字使用其中的选项，"
                        "不得新增、删减、改名、编号或换成另一组维度；正文先给简短的初步判断和"
                        "边界，再自然邀请用户选择。"
                        "请自主判断图片是否能实质帮助用户理解当前回答；只有确实有帮助时，才从"
                        "available_evidence_media 选择对应 knowledge_id。不要因为知识有图片就默认"
                        "附图，也不得输出列表之外的 ID。pending 图片只能作为辅助示意，不能据此"
                        "增加产品或个人适配结论。例如，当用户正在比较色彩方向、且参考图能帮助"
                        "理解冷暖或肤色分类时，图片通常有实质帮助；纯寒暄、售后进度或图片与"
                        "问题无关时不应附图。最终仍须结合当前问题和对话自主判断。"
                        '仅返回 JSON：{"message":"消费者可见回复",'
                        '"media_knowledge_ids":["需要展示的 knowledge_id"]}；'
                        "不需要图片时返回空数组。"
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
        message = message.strip()
        if (
            card.next_state == ConversationState.ASK
            and sum(message.count(mark) for mark in ("?", "？")) > 1
        ):
            raise ValueError("LLM ASK response must contain at most one question")
        if suggested_replies and not all(choice in message for choice in suggested_replies):
            raise ValueError("LLM ASK response must use the allowed suggested replies")
        if is_direct_recommendation and any(mark in message for mark in ("?", "？")):
            raise ValueError("LLM recommendation response must not ask a follow-up question")
        media_knowledge_ids = result.get("media_knowledge_ids")
        if not isinstance(media_knowledge_ids, list) or not all(
            isinstance(item, str) for item in media_knowledge_ids
        ):
            raise ValueError("LLM media selection is invalid")
        available_media_ids = {ref.knowledge_id for ref in card.knowledge_refs if ref.image_url}
        if not set(media_knowledge_ids).issubset(available_media_ids):
            raise ValueError("LLM selected unavailable evidence media")
        return ConsumerReplyGeneration(
            message=message,
            media_knowledge_ids=list(dict.fromkeys(media_knowledge_ids)),
        )

    @staticmethod
    def _suggested_replies(card: EmpathyCard) -> list[str]:
        mappings = (
            ("搓泥发生步骤或已经尝试过的方法", ["护肤后", "防晒后", "上粉底时", "暂时不清楚"]),
            ("肤色冷暖调或期望妆效", ["偏冷调", "偏暖调", "中性调", "暂时不清楚"]),
            ("希望了解的产品品类", ["精华类", "水乳/面霜类", "面膜类", "唇妆类", "暂时不确定"]),
            ("期望的唇妆妆效", ["柔雾轻薄", "水光妆效", "暂时不确定"]),
            ("期望的口红风格", ["日常柔和", "浓郁有氛围", "暂时不确定"]),
        )
        for missing_item, choices in mappings:
            if missing_item in card.missing_information:
                return choices
        return []

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
            except (TimeoutError, URLError, httpx.HTTPError):
                if attempt >= self.retry_limit:
                    raise
        raise RuntimeError("unreachable retry state")

    def _send(self, request: Request, timeout_seconds: float) -> bytes:
        if self._client is None:  # pragma: no cover - constructor invariant
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                return response.read()
        response = self._client.request(
            request.get_method(),
            request.full_url,
            content=request.data,
            headers=dict(request.header_items()),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response.content

    def close(self) -> None:
        """释放 provider 持有的持久 HTTP 连接。"""
        if self._client is not None:
            self._client.close()


class OpenAICompatibleCompetitionModelProvider(OpenAICompatibleIntentProvider):
    """比赛版话术生成 adapter；固定决策由上游规则提供且不可被模型修改。"""

    def generate_reply(self, snapshot: P0ContextSnapshot, decision: P0Decision) -> str:
        context = {
            "fixed_decision": {
                "service_mode": decision.service_mode.value,
                "intent": decision.intent,
                "risk_type": decision.risk_type,
                "send_allowed": decision.send_allowed,
                "reply_audience": decision.reply_audience,
                "next_action": decision.next_action,
            },
            "current_message": snapshot.current_message,
            "known_facts": decision.known_facts,
            "missing_information": decision.missing_information,
            "approved_evidence": [
                {"source": item.source, "excerpt": item.excerpt}
                for item in snapshot.knowledge_evidence
                if item.valid
            ],
        }
        history = [
            {"role": "user" if item.role == "consumer" else "assistant", "content": item.content}
            for item in snapshot.chat_history[-12:]
            if item.role in {"consumer", "agent"}
        ]
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是美妆品牌人工客服的 AI 助手。fixed_decision 是后端已经完成的安全决策，"
                        "不得修改服务模式、风险、发送权限或下一步动作。只根据已提供事实和审核依据"
                        "生成简洁、共情、可供当前 reply_audience 使用的中文草稿。不得编造订单状态、"
                        "政策、功效、医学判断、孕产可用性或赔偿结果。缺少依据时必须明确需要人工核实。"
                        f"\n{CUSTOMER_SERVICE_VOICE_PROMPT}"
                        '仅返回 JSON：{"message": "回复草稿"}。'
                    ),
                },
                *history,
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        result = self._completion(payload)
        message = result.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 8000:
            raise ValueError("LLM competition reply is invalid")
        return message.strip()
