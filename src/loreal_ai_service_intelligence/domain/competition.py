from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceMode(str, Enum):
    AUTO_REPLY = "AUTO_REPLY"
    AGENT_ASSIST = "AGENT_ASSIST"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class MessageDeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


class HumanHandlingStatus(str, Enum):
    NONE = "NONE"
    WAITING = "WAITING"
    CLAIMED = "CLAIMED"


class BusinessActionStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    PENDING_MANUAL = "PENDING_MANUAL"
    SIMULATED = "SIMULATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IssueResultStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    USER_CONFIRMED_RESOLVED = "USER_CONFIRMED_RESOLVED"
    ARCHIVED_UNCONFIRMED = "ARCHIVED_UNCONFIRMED"
    REOPENED = "REOPENED"


class LocalRiskStatus(str, Enum):
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    HANDLING = "HANDLING"
    CLOSED = "CLOSED"


class P0ChatMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=100)
    message_seq: int = Field(ge=1)
    role: Literal["consumer", "agent", "system"]
    content: str = Field(min_length=1, max_length=8000)
    created_at: datetime


class P0ProductSnapshot(BaseModel):
    product_id: str = Field(min_length=1, max_length=100)
    sku: Optional[str] = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    valid_until: Optional[datetime] = None


class P0OrderSnapshot(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    owner_customer_id: str = Field(min_length=1, max_length=100)
    product_id: Optional[str] = Field(default=None, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    amount: Optional[str] = Field(default=None, max_length=100)
    currency: Optional[str] = Field(default=None, max_length=10)
    source_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    valid_until: Optional[datetime] = None


class P0TicketSnapshot(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=100)
    owner_customer_id: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2000)
    source_id: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    valid_until: Optional[datetime] = None


class P0KnowledgeEvidence(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=200)
    excerpt: str = Field(min_length=1, max_length=2000)
    product_id: Optional[str] = Field(default=None, max_length=100)
    scope: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=100)
    observed_at: datetime
    valid_until: Optional[datetime] = None
    valid: bool = True


class P0AttachmentReference(BaseModel):
    attachment_id: str = Field(min_length=1, max_length=100)
    kind: Literal["image", "order_screenshot", "other"]
    authorized: bool = False
    available: bool = False


class P0ContextSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)
    conversation_id: str = Field(min_length=1, max_length=100)
    issue_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    current_message_id: str = Field(min_length=1, max_length=100)
    cutoff_message_seq: int = Field(ge=1)
    current_message: str = Field(min_length=1, max_length=4000)
    chat_history: list[P0ChatMessage] = Field(default_factory=list, max_length=200)
    scene_major: Optional[str] = Field(default=None, max_length=100)
    scene_minor: Optional[str] = Field(default=None, max_length=100)
    scene_source: Optional[str] = Field(default=None, max_length=100)
    scene_missing_reason: Optional[str] = Field(default=None, max_length=300)
    products: list[P0ProductSnapshot] = Field(default_factory=list, max_length=20)
    orders: list[P0OrderSnapshot] = Field(default_factory=list, max_length=20)
    tickets: list[P0TicketSnapshot] = Field(default_factory=list, max_length=20)
    attachments: list[P0AttachmentReference] = Field(default_factory=list, max_length=20)
    knowledge_evidence: list[P0KnowledgeEvidence] = Field(default_factory=list, max_length=50)
    previous_actions: list[str] = Field(default_factory=list, max_length=100)
    unresolved_count: int = Field(default=0, ge=0)
    user_requested_human: bool = False
    takeover_locked: bool = False
    assigned_agent_id: Optional[str] = Field(default=None, max_length=100)
    data_errors: list[str] = Field(default_factory=list)
    source_failures: list[str] = Field(default_factory=list)
    context_version: str = Field(min_length=1, max_length=100)
    captured_at: datetime

    @model_validator(mode="after")
    def validate_cutoff_and_current_message(self) -> P0ContextSnapshot:
        self.current_message = self.current_message.strip()
        if not self.current_message:
            raise ValueError("current_message must not be blank")
        future = [
            item.message_id
            for item in self.chat_history
            if item.message_seq > self.cutoff_message_seq
        ]
        if future:
            raise ValueError("chat_history contains messages after cutoff_message_seq")
        return self


class P0EvidenceReference(BaseModel):
    evidence_id: str
    source_type: Literal["chat", "product", "order", "ticket", "knowledge", "system"]
    source_id: str
    field: str
    excerpt: str
    observed_at: datetime
    valid: bool


class P0TimelineItem(BaseModel):
    source_type: Literal["chat", "order", "ticket", "action"]
    source_id: str
    occurred_at: datetime
    title: str
    detail: str


class P0Decision(BaseModel):
    decision_id: str
    conversation_id: str
    issue_id: str
    current_message_id: str
    cutoff_message_seq: int
    service_mode: ServiceMode
    mode_reason: str
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    intent: str
    trajectory_summary: str
    service_trajectory: list[P0TimelineItem]
    known_facts: list[str]
    inferences: list[str]
    missing_information: list[str]
    emotion: str
    emotion_evidence: list[str]
    urgency: Literal["low", "medium", "high"]
    risk_type: Optional[str] = None
    risk_level: Literal["low", "medium", "high"]
    risk_trigger_quotes: list[str]
    reply_text: Optional[str] = None
    follow_up_question: Optional[str] = None
    next_action: str
    evidence: list[P0EvidenceReference]
    needs_human: bool
    requires_takeover: bool
    needs_ticket: bool
    record_scope: Literal["LOCAL", "EXTERNAL"] = "LOCAL"
    reply_audience: Literal["consumer", "agent"]
    send_allowed: bool
    takeover_locked: bool
    context_version: str
    rule_version: str
    knowledge_version: str
    model_version: Optional[str] = None
    generated_at: datetime


class P0MessageRecord(BaseModel):
    delivery_id: str
    conversation_id: str
    issue_id: str
    message_id: str
    based_on_message_id: str
    body: str
    audience: Literal["consumer"] = "consumer"
    status: MessageDeliveryStatus
    channel: Literal["SIMULATED", "REAL"] = "SIMULATED"
    idempotency_key: str
    error_code: Optional[str] = None
    receipt_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class P0SendRequest(BaseModel):
    decision_id: str
    based_on_message_id: str
    body: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    actor: Literal["system", "agent"]
    simulate_result: Literal["sent", "failed", "unknown"] = "sent"


class P0TakeoverRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)


class P0TakeoverRecord(BaseModel):
    conversation_id: str
    status: HumanHandlingStatus
    takeover_locked: bool
    assigned_agent_id: Optional[str] = None
    reason: str
    updated_at: datetime


class P0BusinessActionRequest(BaseModel):
    action_type: Literal[
        "refund", "replacement", "reship", "address_change", "compensation", "other"
    ]
    description: str = Field(min_length=1, max_length=1000)
    result_type: Literal["pending_manual", "simulated"]
    idempotency_key: str = Field(min_length=1, max_length=200)


class P0BusinessActionRecord(BaseModel):
    action_id: str
    conversation_id: str
    issue_id: str
    action_type: str
    description: str
    status: BusinessActionStatus
    external_execution: bool = False
    idempotency_key: str
    created_at: datetime


class P0RiskUpdateRequest(BaseModel):
    status: LocalRiskStatus
    agent_id: str = Field(min_length=1, max_length=100)
    handling_note: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)


class P0RiskRecord(BaseModel):
    risk_record_id: str
    conversation_id: str
    issue_id: str
    trigger_quote: str
    risk_type: str
    priority: Literal["low", "medium", "high"]
    status: LocalRiskStatus
    assigned_agent_id: Optional[str] = None
    handling_log: list[dict[str, str]] = Field(default_factory=list)
    close_basis: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class P0IssueResultRequest(BaseModel):
    status: Literal["USER_CONFIRMED_RESOLVED", "ARCHIVED_UNCONFIRMED", "REOPENED"]
    actor_id: str = Field(min_length=1, max_length=100)
    evidence_quote: Optional[str] = Field(default=None, max_length=2000)
    reason: Optional[str] = Field(default=None, max_length=1000)


class P0IssueResultRecord(BaseModel):
    issue_id: str
    status: IssueResultStatus
    evidence_quote: Optional[str] = None
    reason: Optional[str] = None
    updated_at: datetime


class P0SuggestionFeedbackRequest(BaseModel):
    decision_id: str
    decision: Literal["adopted", "edited_and_sent", "rejected"]
    actor_id: str = Field(min_length=1, max_length=100)
    final_reply: Optional[str] = Field(default=None, max_length=8000)
    rejection_reason: Optional[
        Literal["fact_error", "wording", "no_evidence", "not_applicable", "other"]
    ] = None

    @model_validator(mode="after")
    def validate_details(self) -> P0SuggestionFeedbackRequest:
        if self.decision == "edited_and_sent" and not (self.final_reply or "").strip():
            raise ValueError("final_reply is required when decision is edited_and_sent")
        if self.decision == "rejected" and self.rejection_reason is None:
            raise ValueError("rejection_reason is required when decision is rejected")
        return self


class P0SuggestionFeedbackRecord(BaseModel):
    feedback_id: str
    conversation_id: str
    decision_id: str
    decision: str
    original_draft: Optional[str]
    final_reply: Optional[str]
    rejection_reason: Optional[str]
    actor_id: str
    created_at: datetime


class P0CorrectionRequest(BaseModel):
    field: Literal["intent", "emotion", "known_fact"]
    new_value: str = Field(min_length=1, max_length=1000)
    actor_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)


class P0CorrectionRecord(BaseModel):
    correction_id: str
    conversation_id: str
    field: str
    old_value: str
    new_value: str
    actor_id: str
    reason: str
    created_at: datetime


class P0SessionRecord(BaseModel):
    conversation_id: str
    issue_id: str
    snapshot: P0ContextSnapshot
    decision: P0Decision
    takeover: P0TakeoverRecord
    messages: list[P0MessageRecord] = Field(default_factory=list)
    actions: list[P0BusinessActionRecord] = Field(default_factory=list)
    risk: Optional[P0RiskRecord] = None
    issue_result: P0IssueResultRecord
    suggestion_feedback: list[P0SuggestionFeedbackRecord] = Field(default_factory=list)
    corrections: list[P0CorrectionRecord] = Field(default_factory=list)
    audit_trail: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
