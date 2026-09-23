from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from loreal_ai_service_intelligence.domain.competition import (
    P0BusinessActionRecord,
    P0BusinessActionRequest,
    P0ContextSnapshot,
    P0CorrectionRecord,
    P0CorrectionRequest,
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
)
from loreal_ai_service_intelligence.infrastructure.repository import StorageRepository
from loreal_ai_service_intelligence.providers.context import ContextDataProvider
from loreal_ai_service_intelligence.services.competition import CompetitionP0Service


def create_competition_router(
    service: CompetitionP0Service,
    repository: StorageRepository,
    context_provider: ContextDataProvider,
) -> APIRouter:
    router = APIRouter(prefix="/v1/competition", tags=["competition-p0"])

    @router.post(
        "/sessions/analyze",
        response_model=P0SessionRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def analyze_snapshot(snapshot: P0ContextSnapshot) -> P0SessionRecord:
        return service.analyze(snapshot)

    @router.post(
        "/conversations/{conversation_id}/analyze",
        response_model=P0SessionRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def analyze_provider_context(
        conversation_id: str,
        cutoff_message_seq: Optional[int] = Query(default=None, ge=1),
    ) -> P0SessionRecord:
        try:
            snapshot = context_provider.load_context(conversation_id, cutoff_message_seq)
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        if snapshot is None:
            raise HTTPException(status_code=404, detail="context snapshot not found")
        return service.analyze(snapshot)

    @router.get("/sessions", response_model=list[P0SessionRecord])
    def list_sessions() -> list[P0SessionRecord]:
        return repository.list_p0_sessions()

    @router.get("/sessions/{conversation_id}", response_model=P0SessionRecord)
    def get_session(conversation_id: str) -> P0SessionRecord:
        session = repository.get_p0_session(conversation_id)
        if session is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return session

    @router.post(
        "/sessions/{conversation_id}/messages",
        response_model=P0MessageRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def send_message(conversation_id: str, request: P0SendRequest) -> P0MessageRecord:
        try:
            record = service.send(conversation_id, request)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if record is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return record

    @router.post(
        "/sessions/{conversation_id}/takeover",
        response_model=P0TakeoverRecord,
    )
    def take_over(conversation_id: str, request: P0TakeoverRequest) -> P0TakeoverRecord:
        try:
            record = service.takeover(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if record is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return record

    @router.post(
        "/sessions/{conversation_id}/actions",
        response_model=P0BusinessActionRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def record_action(
        conversation_id: str, request: P0BusinessActionRequest
    ) -> P0BusinessActionRecord:
        record = service.record_action(conversation_id, request)
        if record is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return record

    @router.patch(
        "/sessions/{conversation_id}/risk",
        response_model=P0RiskRecord,
    )
    def update_risk(conversation_id: str, request: P0RiskUpdateRequest) -> P0RiskRecord:
        try:
            record = service.update_risk(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if record is None:
            raise HTTPException(status_code=404, detail="risk record not found")
        return record

    @router.patch(
        "/sessions/{conversation_id}/issue-result",
        response_model=P0IssueResultRecord,
    )
    def update_issue_result(
        conversation_id: str, request: P0IssueResultRequest
    ) -> P0IssueResultRecord:
        try:
            record = service.update_issue_result(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if record is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return record

    @router.post(
        "/sessions/{conversation_id}/suggestion-feedback",
        response_model=P0SuggestionFeedbackRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def record_suggestion_feedback(
        conversation_id: str, request: P0SuggestionFeedbackRequest
    ) -> P0SuggestionFeedbackRecord:
        try:
            record = service.feedback(conversation_id, request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if record is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return record

    @router.post(
        "/sessions/{conversation_id}/corrections",
        response_model=P0CorrectionRecord,
        status_code=status.HTTP_201_CREATED,
    )
    def correct_understanding(
        conversation_id: str, request: P0CorrectionRequest
    ) -> P0CorrectionRecord:
        record = service.correct(conversation_id, request)
        if record is None:
            raise HTTPException(status_code=404, detail="competition session not found")
        return record

    return router
