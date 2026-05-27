import json
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import get_db
from app.services.session_service import SessionService
from app.schemas.session import SessionCreate, SessionResponse
from app.schemas.message import MessageCreate, MessageResponse
from app.database.models import MessageRole, User
from app.services.auth import get_current_user
from app.services.elevenlabs_agent_service import (
    ElevenLabsAgentError,
    ElevenLabsAgentService,
    ElevenLabsConversationClosed,
)

router = APIRouter()
logger = logging.getLogger(__name__)
elevenlabs_agent = ElevenLabsAgentService()

@router.post("/create", response_model=SessionResponse)
async def create_session(session: SessionCreate = SessionCreate(), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    db_session = await SessionService.create_session(db, user_id=current_user.id)
    return SessionResponse(
        id=db_session.id,
        user_id=db_session.user_id,
        initial_message=None,
    )

@router.post(
    "/{session_id}/messages",
    status_code=200,
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent event stream with token, done, or error payloads.",
            "content": {
                "text/event-stream": {
                    "example": (
                        'data: {"type":"token","content":"Hello"}\n\n'
                        'data: {"type":"done","message":{"id":1,"role":"agent",'
                        '"content":"Hello","created_at":"2026-05-15T10:00:00"}}\n\n'
                    )
                }
            },
        },
        404: {"description": "Session not found or unauthorized"},
    },
)
async def send_message(session_id: int, message: MessageCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await SessionService.get_session(db, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found or unauthorized")
    
    # Add user message
    await SessionService.create_message(db, session_id, MessageRole.USER, message.content)
    
    # Get conversation history and generate agent response
    messages = await SessionService.get_session_messages(db, session_id)

    async def stream_agent_response():
        chunks: list[str] = []
        try:
            async for chunk in elevenlabs_agent.generate_agent_response(
                messages,
                session_id=session_id,
            ):
                chunks.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            agent_content = "".join(chunks).strip()
            if not agent_content:
                logger.warning("ElevenLabs returned no agent response for session_id=%s", session_id)
                yield f"data: {json.dumps({'type': 'error', 'detail': 'No agent response received'})}\n\n"
                return

            agent_message = await SessionService.create_message(db, session_id, MessageRole.AGENT, agent_content)
            done_payload = {
                "type": "done",
                "message": {
                    "id": agent_message.id,
                    "role": agent_message.role.value,
                    "content": agent_message.content,
                    "created_at": agent_message.created_at.isoformat(),
                },
            }
            yield f"data: {json.dumps(done_payload)}\n\n"
        except ElevenLabsConversationClosed as exc:
            logger.warning(
                "ElevenLabs closed conversation before response for session_id=%s: %s",
                session_id,
                exc,
            )
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Agent conversation closed before a response was received'})}\n\n"
        except ElevenLabsAgentError:
            logger.exception("ElevenLabs agent failed for session_id=%s", session_id)
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Failed to generate agent response'})}\n\n"
        except Exception:
            logger.exception("Failed to generate ElevenLabs agent response")
            yield f"data: {json.dumps({'type': 'error', 'detail': 'Failed to generate agent response'})}\n\n"

    return StreamingResponse(stream_agent_response(), media_type="text/event-stream")


@router.get("/{session_id}/messages", response_model=List[MessageResponse])
async def get_session_messages(session_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await SessionService.get_session(db, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found or unauthorized")

    messages = await SessionService.get_session_messages(db, session_id)
    return [
        MessageResponse(
            id=msg.id,
            role=msg.role.value,
            content=msg.content,
            created_at=msg.created_at.isoformat()
        )
        for msg in messages
    ]


@router.delete("/delete-all")
async def delete_all_sessions(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete
    from app.database.models import Session
    await db.execute(delete(Session))
    await db.commit()
    await elevenlabs_agent.close_all_sessions()
    return {
        "message": "All sessions deleted successfully" 
    }
