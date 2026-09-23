from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from loreal_ai_service_intelligence.config import Settings
from loreal_ai_service_intelligence.domain.competition import (
    BusinessActionStatus,
    HumanHandlingStatus,
    IssueResultStatus,
    LocalRiskStatus,
    MessageDeliveryStatus,
    P0BusinessActionRecord,
    P0BusinessActionRequest,
    P0ContextSnapshot,
    P0CorrectionRecord,
    P0CorrectionRequest,
    P0Decision,
    P0EvidenceReference,
    P0IssueResultRecord,
    P0IssueResultRequest,
    P0MessageRecord,
    P0RiskRecord,
    P0RiskUpdateRequest,
    P0SendRequest,
    P0SessionRecord,
    P0SuggestionFeedbackRecord,
    P0SuggestionFeedbackRequest,
    P0TakeoverRecord,
    P0TakeoverRequest,
    P0TimelineItem,
    ServiceMode,
)
from loreal_ai_service_intelligence.infrastructure.repository import StorageRepository, utc_now


class CompetitionP0Service:
    """Deterministic P0 workflow and permission boundary for the competition demo."""

    _risk_terms = ("泛红", "刺痛", "红肿", "灼痛", "呼吸困难", "不良反应", "就医")
    _complaint_terms = ("投诉", "曝光", "律师", "起诉")
    _security_terms = (
        "盗号",
        "陌生扣款",
        "密码",
        "他人地址",
        "别人的地址",
        "另一个人的地址",
        "支付异常",
        "账号异常",
    )
    _dissatisfied_terms = ("不满", "太差", "答非所问", "怎么还", "一直没有", "很生气")
    _unresolved_terms = ("没解决", "未解决", "还是不行", "还没处理", "没有结果")
    _after_sales_terms = ("退款", "退货", "换货", "补发", "破损", "错发", "赔偿", "改址")
    _logistics_terms = ("物流", "快递", "运输", "到哪", "没收到")
    _usage_terms = ("怎么用", "使用方法", "步骤", "用法")
    _product_terms = ("规格", "成分", "容量", "保质期", "产品信息")

    def __init__(self, repository: StorageRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def analyze(self, snapshot: P0ContextSnapshot) -> P0SessionRecord:
        existing = self.repository.get_p0_session(snapshot.conversation_id)
        if existing and existing.snapshot.current_message_id == snapshot.current_message_id:
            return existing
        now = utc_now()
        decision = self._decide(snapshot, now)
        takeover_locked = (
            snapshot.takeover_locked
            or decision.requires_takeover
            or bool(existing and existing.takeover.takeover_locked)
        )
        takeover = P0TakeoverRecord(
            conversation_id=snapshot.conversation_id,
            status=(
                HumanHandlingStatus.CLAIMED
                if snapshot.assigned_agent_id
                else HumanHandlingStatus.WAITING
                if decision.requires_takeover
                else HumanHandlingStatus.NONE
            ),
            takeover_locked=takeover_locked,
            assigned_agent_id=snapshot.assigned_agent_id,
            reason=decision.mode_reason,
            updated_at=now,
        )
        decision.takeover_locked = takeover_locked
        decision.send_allowed = decision.send_allowed and not takeover_locked
        risk = self._risk_record(snapshot, decision, now)
        if existing and existing.risk and risk is None:
            risk = existing.risk
        result = (
            existing.issue_result
            if existing and existing.issue_id == snapshot.issue_id
            else P0IssueResultRecord(
                issue_id=snapshot.issue_id,
                status=IssueResultStatus.OPEN,
                updated_at=now,
            )
        )
        session = P0SessionRecord(
            conversation_id=snapshot.conversation_id,
            issue_id=snapshot.issue_id,
            snapshot=snapshot,
            decision=decision,
            takeover=takeover,
            messages=list(existing.messages) if existing else [],
            actions=list(existing.actions) if existing else [],
            risk=risk,
            issue_result=result,
            suggestion_feedback=list(existing.suggestion_feedback) if existing else [],
            corrections=list(existing.corrections) if existing else [],
            audit_trail=list(existing.audit_trail) if existing else [],
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self._audit(
            session,
            "analysis_completed",
            {
                "decision_id": decision.decision_id,
                "service_mode": decision.service_mode.value,
                "context_version": snapshot.context_version,
                "current_message_id": snapshot.current_message_id,
            },
        )
        self.repository.save_p0_session(session)
        return session

    def _decide(self, snapshot: P0ContextSnapshot, now) -> P0Decision:
        text = snapshot.current_message
        risk_quotes = [term for term in self._risk_terms if term in text]
        complaint = any(term in text for term in self._complaint_terms)
        security = any(term in text for term in self._security_terms)
        unresolved = snapshot.unresolved_count + int(
            any(term in text for term in self._unresolved_terms)
        )
        ownership_errors = [
            item.order_id
            for item in snapshot.orders
            if item.owner_customer_id != snapshot.customer_id
        ] + [
            item.ticket_id
            for item in snapshot.tickets
            if item.owner_customer_id != snapshot.customer_id
        ]
        conflicts = self._has_conflict(snapshot)
        data_failure = bool(snapshot.source_failures or snapshot.data_errors or ownership_errors)
        invalid_evidence = any(not item.valid for item in snapshot.knowledge_evidence)
        force_reason = None
        if snapshot.takeover_locked:
            force_reason = "会话已由人工接管，自动发送锁保持有效"
        elif snapshot.user_requested_human:
            force_reason = "消费者明确要求人工客服"
        elif risk_quotes:
            force_reason = f"命中当前安全风险信号：{'、'.join(risk_quotes)}"
        elif complaint:
            force_reason = "消费者提出投诉、曝光或法律升级诉求"
        elif security:
            force_reason = "涉及账号、支付或隐私安全异常"
        elif ownership_errors:
            force_reason = "数据归属校验失败，禁止展示或自动回复"
        elif conflicts:
            force_reason = "订单或工单存在无法确定权威来源的关键事实冲突"
        elif data_failure:
            force_reason = "必需数据源或工具失败"
        elif invalid_evidence:
            force_reason = "知识证据已失效或不可核验"
        elif unresolved >= 2:
            force_reason = "同一问题第二次明确未解决"

        intent = self._intent(text)
        mode = ServiceMode.HUMAN_REQUIRED if force_reason else ServiceMode.AGENT_ASSIST
        reason = force_reason or "非自动白名单或仍需人工核对"
        if force_reason is None:
            auto_allowed, auto_reason = self._auto_reply_allowed(snapshot, intent)
            if (
                auto_allowed
                and unresolved == 0
                and not any(term in text for term in self._dissatisfied_terms)
            ):
                mode = ServiceMode.AUTO_REPLY
                reason = auto_reason
            elif unresolved == 1:
                reason = "同一问题第一次明确未解决，进入人工辅助"
            elif len(snapshot.orders) > 1:
                reason = "存在多个候选订单，需要人工选择"
            elif snapshot.attachments:
                reason = "存在需要人工查看的附件，当前未启用图片识别"
            elif any(term in text for term in self._after_sales_terms):
                reason = "售后请求只生成草稿和本地待处理动作"

        evidence = self._evidence(snapshot, now)
        trajectory = self._timeline(snapshot)
        promises = [
            item.summary
            for item in snapshot.tickets
            if any(term in item.summary for term in ("承诺", "答应", "预计", "跟进"))
        ]
        unresolved_items = [
            f"工单 {item.ticket_id} 当前为 {item.status}"
            for item in snapshot.tickets
            if item.status.lower() not in {"closed", "resolved", "completed"}
        ]
        known = [*promises, *unresolved_items]
        if snapshot.orders:
            known.extend(f"订单 {item.order_id} 当前为 {item.status}" for item in snapshot.orders)
        missing = []
        if not snapshot.scene_minor:
            missing.append(snapshot.scene_missing_reason or "官方场景标签未映射")
        if intent in {"product_info", "usage"} and not snapshot.products:
            missing.append("明确商品或 SKU")
        if intent in {"order_status", "logistics"} and not snapshot.orders:
            missing.append("已完成归属校验的订单快照")
        emotion, emotion_evidence = self._emotion(text)
        urgency = (
            "high"
            if risk_quotes or complaint or security
            else "medium"
            if emotion != "neutral"
            else "low"
        )
        draft = self._draft(snapshot, intent, mode, promises, unresolved_items, missing)
        risk_type = (
            "safety"
            if risk_quotes
            else "complaint"
            if complaint
            else "account_or_payment"
            if security
            else None
        )
        return P0Decision(
            decision_id=f"decision_{uuid4().hex}",
            conversation_id=snapshot.conversation_id,
            issue_id=snapshot.issue_id,
            current_message_id=snapshot.current_message_id,
            cutoff_message_seq=snapshot.cutoff_message_seq,
            service_mode=mode,
            mode_reason=reason,
            intent=intent,
            trajectory_summary="；".join(known) or "当前仅有本轮消费者原话",
            service_trajectory=trajectory,
            known_facts=known,
            inferences=[f"消费者情绪可能为 {emotion}"] if emotion != "neutral" else [],
            missing_information=missing,
            emotion=emotion,
            emotion_evidence=emotion_evidence,
            urgency=urgency,
            risk_type=risk_type,
            risk_level="high" if risk_type else "low",
            risk_trigger_quotes=risk_quotes,
            reply_text=draft,
            follow_up_question=self._follow_up(missing)
            if mode == ServiceMode.AGENT_ASSIST
            else None,
            next_action=self._next_action(mode, risk_type, intent),
            evidence=evidence,
            needs_human=mode != ServiceMode.AUTO_REPLY,
            requires_takeover=mode == ServiceMode.HUMAN_REQUIRED,
            needs_ticket=mode != ServiceMode.AUTO_REPLY,
            reply_audience="consumer" if mode == ServiceMode.AUTO_REPLY else "agent",
            send_allowed=mode == ServiceMode.AUTO_REPLY,
            takeover_locked=snapshot.takeover_locked,
            context_version=snapshot.context_version,
            rule_version=self.settings.rule_version,
            knowledge_version=self.settings.knowledge_version,
            model_version=self.settings.llm_model if self.settings.llm_enabled else None,
            generated_at=now,
        )

    def send(self, conversation_id: str, request: P0SendRequest) -> P0MessageRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None:
            return None
        existing = next(
            (item for item in session.messages if item.idempotency_key == request.idempotency_key),
            None,
        )
        if existing:
            return existing
        if request.decision_id != session.decision.decision_id:
            raise ValueError("decision is stale")
        if request.based_on_message_id != session.snapshot.current_message_id:
            raise ValueError("current message changed; re-analysis is required")
        if request.actor == "system" and (
            session.decision.service_mode != ServiceMode.AUTO_REPLY
            or not session.decision.send_allowed
            or session.takeover.takeover_locked
        ):
            raise PermissionError("automatic send is not allowed")
        if request.actor == "agent" and session.takeover.status == HumanHandlingStatus.NONE:
            raise PermissionError("agent must claim or take over the conversation before sending")
        now = utc_now()
        status = {
            "sent": MessageDeliveryStatus.SENT,
            "failed": MessageDeliveryStatus.FAILED,
            "unknown": MessageDeliveryStatus.UNKNOWN,
        }[request.simulate_result]
        record = P0MessageRecord(
            delivery_id=f"delivery_{uuid4().hex}",
            conversation_id=conversation_id,
            issue_id=session.issue_id,
            message_id=f"out_{uuid4().hex}",
            based_on_message_id=request.based_on_message_id,
            body=request.body.strip(),
            status=status,
            idempotency_key=request.idempotency_key,
            error_code="SIMULATED_SEND_FAILURE" if status == MessageDeliveryStatus.FAILED else None,
            receipt_id=f"sim_{uuid4().hex}" if status == MessageDeliveryStatus.SENT else None,
            created_at=now,
            updated_at=now,
        )
        if status in {MessageDeliveryStatus.FAILED, MessageDeliveryStatus.UNKNOWN}:
            session.takeover.takeover_locked = True
            session.decision.send_allowed = False
        session.messages.append(record)
        session.updated_at = now
        self._audit(session, "message_delivery_recorded", record.model_dump(mode="json"))
        self.repository.save_p0_session(session)
        return record

    def takeover(self, conversation_id: str, request: P0TakeoverRequest) -> P0TakeoverRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None:
            return None
        if (
            session.takeover.status == HumanHandlingStatus.CLAIMED
            and session.takeover.assigned_agent_id != request.agent_id
        ):
            raise ValueError("conversation is already claimed by another agent")
        for message in session.messages:
            if message.status in {MessageDeliveryStatus.DRAFT, MessageDeliveryStatus.PENDING}:
                message.status = MessageDeliveryStatus.CANCELLED
                message.updated_at = utc_now()
        now = utc_now()
        session.takeover = P0TakeoverRecord(
            conversation_id=conversation_id,
            status=HumanHandlingStatus.CLAIMED,
            takeover_locked=True,
            assigned_agent_id=request.agent_id,
            reason="客服主动接管或认领",
            updated_at=now,
        )
        session.decision.takeover_locked = True
        session.decision.send_allowed = False
        session.updated_at = now
        self._audit(
            session,
            "takeover_claimed",
            {"agent_id": request.agent_id, "idempotency_key": request.idempotency_key},
        )
        self.repository.save_p0_session(session)
        return session.takeover

    def record_action(
        self, conversation_id: str, request: P0BusinessActionRequest
    ) -> P0BusinessActionRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None:
            return None
        existing = next(
            (item for item in session.actions if item.idempotency_key == request.idempotency_key),
            None,
        )
        if existing:
            return existing
        status = (
            BusinessActionStatus.SIMULATED
            if request.result_type == "simulated"
            else BusinessActionStatus.PENDING_MANUAL
        )
        action = P0BusinessActionRecord(
            action_id=f"action_{uuid4().hex}",
            conversation_id=conversation_id,
            issue_id=session.issue_id,
            action_type=request.action_type,
            description=request.description,
            status=status,
            external_execution=False,
            idempotency_key=request.idempotency_key,
            created_at=utc_now(),
        )
        session.actions.append(action)
        session.updated_at = action.created_at
        self._audit(session, "local_business_action_recorded", action.model_dump(mode="json"))
        self.repository.save_p0_session(session)
        return action

    def update_risk(
        self, conversation_id: str, request: P0RiskUpdateRequest
    ) -> P0RiskRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None or session.risk is None:
            return None
        order = {
            LocalRiskStatus.DETECTED: 0,
            LocalRiskStatus.ACKNOWLEDGED: 1,
            LocalRiskStatus.HANDLING: 2,
            LocalRiskStatus.CLOSED: 3,
        }
        if order[request.status] < order[session.risk.status]:
            raise ValueError("risk status cannot move backwards")
        if request.status == LocalRiskStatus.CLOSED and not request.evidence_ids:
            raise ValueError("evidence_ids are required when risk is closed")
        now = utc_now()
        session.risk.status = request.status
        session.risk.assigned_agent_id = request.agent_id
        session.risk.handling_log.append(
            {
                "agent_id": request.agent_id,
                "status": request.status.value,
                "note": request.handling_note,
                "evidence_ids": ",".join(request.evidence_ids),
                "created_at": now.isoformat(),
            }
        )
        if request.status == LocalRiskStatus.CLOSED:
            session.risk.close_basis = request.handling_note
        session.risk.updated_at = now
        session.updated_at = now
        self._audit(session, "risk_updated", session.risk.model_dump(mode="json"))
        self.repository.save_p0_session(session)
        return session.risk

    def update_issue_result(
        self, conversation_id: str, request: P0IssueResultRequest
    ) -> P0IssueResultRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None:
            return None
        target = IssueResultStatus(request.status)
        pending_actions = any(
            item.status in {BusinessActionStatus.SUGGESTED, BusinessActionStatus.PENDING_MANUAL}
            for item in session.actions
        )
        open_risk = session.risk is not None and session.risk.status != LocalRiskStatus.CLOSED
        if target == IssueResultStatus.USER_CONFIRMED_RESOLVED:
            if not (request.evidence_quote or "").strip():
                raise ValueError("explicit consumer confirmation quote is required")
            if pending_actions or open_risk:
                raise ValueError("issue cannot be resolved while actions or risks remain open")
        if target == IssueResultStatus.ARCHIVED_UNCONFIRMED and not (request.reason or "").strip():
            raise ValueError("archive reason is required")
        now = utc_now()
        session.issue_result = P0IssueResultRecord(
            issue_id=session.issue_id,
            status=target,
            evidence_quote=(request.evidence_quote or "").strip() or None,
            reason=(request.reason or "").strip() or None,
            updated_at=now,
        )
        if target == IssueResultStatus.REOPENED:
            session.takeover.takeover_locked = True
            session.decision.takeover_locked = True
            session.decision.send_allowed = False
        session.updated_at = now
        self._audit(session, "issue_result_updated", session.issue_result.model_dump(mode="json"))
        self.repository.save_p0_session(session)
        return session.issue_result

    def feedback(
        self, conversation_id: str, request: P0SuggestionFeedbackRequest
    ) -> P0SuggestionFeedbackRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None:
            return None
        if request.decision_id != session.decision.decision_id:
            raise ValueError("decision is stale")
        now = utc_now()
        record = P0SuggestionFeedbackRecord(
            feedback_id=f"feedback_{uuid4().hex}",
            conversation_id=conversation_id,
            decision_id=request.decision_id,
            decision=request.decision,
            original_draft=session.decision.reply_text,
            final_reply=(request.final_reply or "").strip() or None,
            rejection_reason=request.rejection_reason,
            actor_id=request.actor_id,
            created_at=now,
        )
        session.suggestion_feedback.append(record)
        session.updated_at = now
        self._audit(session, "suggestion_feedback_recorded", record.model_dump(mode="json"))
        self.repository.save_p0_session(session)
        return record

    def correct(
        self, conversation_id: str, request: P0CorrectionRequest
    ) -> P0CorrectionRecord | None:
        session = self.repository.get_p0_session(conversation_id)
        if session is None:
            return None
        old_value = {
            "intent": session.decision.intent,
            "emotion": session.decision.emotion,
            "known_fact": "；".join(session.decision.known_facts),
        }[request.field]
        now = utc_now()
        record = P0CorrectionRecord(
            correction_id=f"correction_{uuid4().hex}",
            conversation_id=conversation_id,
            field=request.field,
            old_value=old_value,
            new_value=request.new_value,
            actor_id=request.actor_id,
            reason=request.reason,
            created_at=now,
        )
        session.corrections.append(record)
        session.updated_at = now
        self._audit(session, "understanding_corrected", record.model_dump(mode="json"))
        self.repository.save_p0_session(session)
        return record

    def _auto_reply_allowed(self, snapshot: P0ContextSnapshot, intent: str) -> tuple[bool, str]:
        now = utc_now()
        valid_knowledge = [
            item
            for item in snapshot.knowledge_evidence
            if item.valid and (item.valid_until is None or item.valid_until >= now)
        ]
        valid_orders = [
            item
            for item in snapshot.orders
            if item.owner_customer_id == snapshot.customer_id
            and (item.valid_until is None or item.valid_until >= now)
        ]
        if not snapshot.scene_minor:
            return False, "官方标签尚未映射"
        if intent in {"product_info", "usage"}:
            return (
                bool(snapshot.products and valid_knowledge),
                "W01/W02 白名单及商品知识门禁通过",
            )
        if intent in {"order_status", "logistics"}:
            return (
                len(valid_orders) == 1,
                "W03/W04 白名单及订单归属与有效性门禁通过",
            )
        return False, "当前意图不在 W01 至 W04 自动白名单"

    @staticmethod
    def _has_conflict(snapshot: P0ContextSnapshot) -> bool:
        if not snapshot.orders or not snapshot.tickets:
            return False
        latest_order = max(snapshot.orders, key=lambda item: item.observed_at)
        latest_ticket = max(snapshot.tickets, key=lambda item: item.observed_at)
        if latest_order.observed_at != latest_ticket.observed_at:
            return False
        order_statuses = {latest_order.status.lower()}
        ticket_statuses = {latest_ticket.status.lower()}
        completed = {"completed", "refunded", "resolved", "closed"}
        pending = {"pending", "processing", "refund_pending"}
        return bool(order_statuses & completed and ticket_statuses & pending) or bool(
            ticket_statuses & completed and order_statuses & pending
        )

    def _intent(self, text: str) -> str:
        if any(term in text for term in self._after_sales_terms):
            return "after_sales"
        if any(term in text for term in self._logistics_terms):
            return "logistics"
        if any(term in text for term in self._usage_terms):
            return "usage"
        if any(term in text for term in self._product_terms):
            return "product_info"
        return "general_consultation"

    def _emotion(self, text: str) -> tuple[str, list[str]]:
        quotes = [
            term for term in (*self._complaint_terms, *self._dissatisfied_terms) if term in text
        ]
        if any(term in text for term in self._complaint_terms):
            return "angry", quotes
        if quotes or any(term in text for term in self._unresolved_terms):
            return "frustrated", quotes or [text]
        return "neutral", []

    @staticmethod
    def _follow_up(missing: list[str]) -> str | None:
        return f"请确认{missing[0]}。" if missing else None

    @staticmethod
    def _next_action(mode: ServiceMode, risk_type: str | None, intent: str) -> str:
        if mode == ServiceMode.HUMAN_REQUIRED:
            return "锁定自动发送并由人工认领处理" if risk_type else "人工核对冲突或失败后处理"
        if mode == ServiceMode.AGENT_ASSIST:
            return (
                "人工审核草稿并记录本地待处理动作" if intent == "after_sales" else "人工审核后发送"
            )
        return "校验当前消息版本后通过比赛模拟通道发送"

    @staticmethod
    def _draft(
        snapshot: P0ContextSnapshot,
        intent: str,
        mode: ServiceMode,
        promises: list[str],
        unresolved_items: list[str],
        missing: list[str],
    ) -> str | None:
        if mode == ServiceMode.HUMAN_REQUIRED:
            return None
        if intent == "after_sales":
            history = "我看到你之前已经联系过客服。" if promises else "我已了解你这次的售后诉求。"
            status = unresolved_items[0] if unresolved_items else "当前处理状态仍需人工核对"
            return f"{history}{status}；接下来由客服继续核实并记录处理进展。"
        if missing:
            return f"我先核对你的需求。请确认{missing[0]}，确认后我再给出准确答复。"
        if intent in {"order_status", "logistics"} and snapshot.orders:
            order = snapshot.orders[0]
            return (
                f"我已核对订单 {order.order_id}，当前状态为 {order.status}"
                f"（快照时间：{order.observed_at.isoformat()}）。"
            )
        if snapshot.knowledge_evidence:
            return snapshot.knowledge_evidence[0].excerpt
        return "我已理解你的问题，客服会结合当前有效资料核对后回复。"

    @staticmethod
    def _timeline(snapshot: P0ContextSnapshot) -> list[P0TimelineItem]:
        items = [
            P0TimelineItem(
                source_type="chat",
                source_id=item.message_id,
                occurred_at=item.created_at,
                title="消费者消息" if item.role == "consumer" else "客服消息",
                detail=item.content,
            )
            for item in snapshot.chat_history
        ]
        items.extend(
            P0TimelineItem(
                source_type="order",
                source_id=item.order_id,
                occurred_at=item.observed_at,
                title=f"订单状态 {item.status}",
                detail=f"来源 {item.source_id}",
            )
            for item in snapshot.orders
            if item.owner_customer_id == snapshot.customer_id
        )
        items.extend(
            P0TimelineItem(
                source_type="ticket",
                source_id=item.ticket_id,
                occurred_at=item.observed_at,
                title=f"工单状态 {item.status}",
                detail=item.summary,
            )
            for item in snapshot.tickets
            if item.owner_customer_id == snapshot.customer_id
        )
        return sorted(items, key=lambda item: item.occurred_at)

    @staticmethod
    def _evidence(snapshot: P0ContextSnapshot, now: datetime) -> list[P0EvidenceReference]:
        evidence = [
            P0EvidenceReference(
                evidence_id=f"chat:{item.message_id}",
                source_type="chat",
                source_id=item.message_id,
                field="content",
                excerpt=item.content,
                observed_at=item.created_at,
                valid=True,
            )
            for item in snapshot.chat_history
        ]
        evidence.extend(
            P0EvidenceReference(
                evidence_id=f"order:{item.order_id}",
                source_type="order",
                source_id=item.source_id,
                field="status",
                excerpt=item.status,
                observed_at=item.observed_at,
                valid=item.valid_until is None or item.valid_until >= now,
            )
            for item in snapshot.orders
            if item.owner_customer_id == snapshot.customer_id
        )
        evidence.extend(
            P0EvidenceReference(
                evidence_id=f"ticket:{item.ticket_id}",
                source_type="ticket",
                source_id=item.source_id,
                field="summary",
                excerpt=item.summary,
                observed_at=item.observed_at,
                valid=item.valid_until is None or item.valid_until >= now,
            )
            for item in snapshot.tickets
            if item.owner_customer_id == snapshot.customer_id
        )
        evidence.extend(
            P0EvidenceReference(
                evidence_id=item.evidence_id,
                source_type="knowledge",
                source_id=item.source,
                field="excerpt",
                excerpt=item.excerpt,
                observed_at=item.observed_at,
                valid=item.valid and (item.valid_until is None or item.valid_until >= now),
            )
            for item in snapshot.knowledge_evidence
        )
        return evidence

    @staticmethod
    def _risk_record(
        snapshot: P0ContextSnapshot, decision: P0Decision, now: datetime
    ) -> P0RiskRecord | None:
        if decision.risk_type is None:
            return None
        return P0RiskRecord(
            risk_record_id=f"risk_{uuid4().hex}",
            conversation_id=snapshot.conversation_id,
            issue_id=snapshot.issue_id,
            trigger_quote=snapshot.current_message,
            risk_type=decision.risk_type,
            priority=decision.risk_level,
            status=LocalRiskStatus.DETECTED,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _audit(session: P0SessionRecord, event_type: str, payload: dict[str, object]) -> None:
        session.audit_trail.append(
            {"event_type": event_type, "created_at": utc_now().isoformat(), "payload": payload}
        )
