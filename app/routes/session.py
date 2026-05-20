import json
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

router = APIRouter()

@router.post("/create", response_model=SessionResponse)
async def create_session(session: SessionCreate = SessionCreate(), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    db_session = await SessionService.create_session(db, user_id=current_user.id)
    return SessionResponse(id=db_session.id, user_id=db_session.user_id)

@router.post("/{session_id}/messages")
async def send_message(session_id: int, message: MessageCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session = await SessionService.get_session(db, session_id)
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found or unauthorized")
    
    # Add user message
    await SessionService.create_message(db, session_id, MessageRole.USER, message.content)
    
    # Get conversation history and generate agent response
    messages = await SessionService.get_session_messages(db, session_id)
    from app.services.openai_service import OpenAIService
    openai_srv = OpenAIService()

    async def stream_agent_response():
        chunks: list[str] = []
        try:
            async for chunk in openai_srv.generate_agent_response(messages):
                chunks.append(chunk)
                yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

            agent_content = "".join(chunks).strip()
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
        except Exception:
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
    return {
        "message": "All sessions deleted successfully" 
    }
