"""Conversation management routes.

GET    /api/cases/{slug}/conversations            — list
POST   /api/cases/{slug}/conversations            — create
GET    /api/cases/{slug}/conversations/{conv_id}  — get with messages
PATCH  /api/cases/{slug}/conversations/{conv_id}  — rename
DELETE /api/cases/{slug}/conversations/{conv_id}  — delete
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from casestack.api.deps import get_app_state

router = APIRouter()


class CreateConversationRequest(BaseModel):
    title: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str


@router.get("/cases/{slug}/conversations")
def list_conversations(slug: str):
    state = get_app_state()
    if not state.get_case(slug):
        raise HTTPException(404, "Case not found")
    return state.list_conversations(slug)


@router.post("/cases/{slug}/conversations", status_code=201)
def create_conversation(slug: str, body: CreateConversationRequest):
    state = get_app_state()
    if not state.get_case(slug):
        raise HTTPException(404, "Case not found")
    return state.create_conversation(slug, title=body.title)


@router.get("/cases/{slug}/conversations/{conv_id}")
def get_conversation(slug: str, conv_id: str):
    state = get_app_state()
    conv = state.get_conversation(conv_id)
    if not conv or conv["case_slug"] != slug:
        raise HTTPException(404, "Conversation not found")
    messages = state.get_conversation_messages(conv_id)
    return {"conversation": conv, "messages": messages}


@router.patch("/cases/{slug}/conversations/{conv_id}")
def update_conversation(slug: str, conv_id: str, body: UpdateConversationRequest):
    state = get_app_state()
    conv = state.get_conversation(conv_id)
    if not conv or conv["case_slug"] != slug:
        raise HTTPException(404, "Conversation not found")
    state.update_conversation_title(conv_id, body.title)
    return state.get_conversation(conv_id)


@router.delete("/cases/{slug}/conversations/{conv_id}", status_code=204)
def delete_conversation(slug: str, conv_id: str):
    state = get_app_state()
    conv = state.get_conversation(conv_id)
    if not conv or conv["case_slug"] != slug:
        raise HTTPException(404, "Conversation not found")
    state.delete_conversation(conv_id)
