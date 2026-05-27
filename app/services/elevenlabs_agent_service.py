from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import websockets
from websockets.exceptions import ConnectionClosed

from app.config.settings import settings
from app.database.models import Message, MessageRole


class ElevenLabsAgentError(RuntimeError):
    """Base error for ElevenLabs agent response failures."""


class ElevenLabsConversationClosed(ElevenLabsAgentError):
    """Raised when ElevenLabs closes before sending an agent response."""


class ElevenLabsAgentService:
    def __init__(self):
        self.api_key = settings.ELEVENLABS_API_KEY
        self.agent_id = settings.ELEVENLABS_AGENT_ID
        self.signed_url_endpoint = "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"
        self.response_timeout_s = 120
        self.response_idle_timeout_s = 2.0
        self.startup_greeting_timeout_s = 2.0
        self.startup_greeting_idle_timeout_s = 0.5
        self._sessions: dict[int, ElevenLabsConversationSession] = {}
        self._sessions_lock = asyncio.Lock()

    def _validate_settings(self) -> None:
        if not self.api_key:
            raise ValueError("ELEVENLABS_API_KEY is not configured")
        if not self.agent_id:
            raise ValueError("ELEVENLABS_AGENT_ID is not configured")

    @staticmethod
    def _format_history(messages: List[Message]) -> str:
        history_messages = messages[:-1] if messages else []
        if not history_messages:
            return ""

        lines: list[str] = []
        for msg in history_messages[-20:]:
            role = "assistant" if msg.role == MessageRole.AGENT else "user"
            content = (msg.content or "").strip()
            if content:
                lines.append(f"{role}: {content}")

        return "\n".join(lines)[-6000:]

    @staticmethod
    def _latest_user_message(messages: List[Message]) -> str:
        for msg in reversed(messages):
            if msg.role == MessageRole.USER:
                return (msg.content or "").strip()
        return ""

    async def _connect(self, uri: str, headers: dict[str, str]):
        try:
            return await websockets.connect(uri, additional_headers=headers)
        except TypeError:
            return await websockets.connect(uri, extra_headers=headers)

    def _fetch_signed_url_sync(self) -> str:
        query = urlencode({"agent_id": self.agent_id})
        request = Request(
            f"{self.signed_url_endpoint}?{query}",
            headers={"xi-api-key": self.api_key},
            method="GET",
        )
        with urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        signed_url = payload.get("signed_url")
        if not signed_url:
            raise RuntimeError("ElevenLabs did not return a signed conversation URL")
        return signed_url

    async def _get_signed_url(self) -> str:
        return await asyncio.to_thread(self._fetch_signed_url_sync)

    @staticmethod
    def _conversation_initiation_payload() -> dict:
        return {
            "type": "conversation_initiation_client_data",
            "conversation_config_override": {
                "conversation": {"text_only": True},
            },
        }

    async def generate_agent_response(
        self,
        messages: List[Message],
        session_id: int | None = None,
    ) -> AsyncIterator[str]:
        text = await self.generate_agent_response_text(messages, session_id=session_id)
        if text:
            yield text

    async def generate_agent_response_text(
        self,
        messages: List[Message],
        session_id: int | None = None,
    ) -> str:
        self._validate_settings()

        user_message = self._latest_user_message(messages)
        if not user_message:
            raise ValueError("No user message found for ElevenLabs agent")

        if session_id is None:
            return await self._generate_one_shot_response(messages, user_message)

        conversation = await self._get_or_create_session(session_id)
        try:
            return await conversation.send_user_message(messages, user_message)
        except ElevenLabsConversationClosed:
            await self.close_session(session_id)
            raise
        except Exception:
            if conversation.closed:
                await self.close_session(session_id)
            raise

    async def _generate_one_shot_response(
        self,
        messages: List[Message],
        user_message: str,
    ) -> str:
        conversation = ElevenLabsConversationSession(self)
        try:
            return await conversation.send_user_message(messages, user_message)
        finally:
            await conversation.close()

    async def _get_or_create_session(self, session_id: int) -> "ElevenLabsConversationSession":
        async with self._sessions_lock:
            conversation = self._sessions.get(session_id)
            if conversation is None or conversation.closed:
                conversation = ElevenLabsConversationSession(self)
                self._sessions[session_id] = conversation
            return conversation

    async def close_session(self, session_id: int) -> None:
        async with self._sessions_lock:
            conversation = self._sessions.pop(session_id, None)
        if conversation is not None:
            await conversation.close()

    async def close_all_sessions(self) -> None:
        async with self._sessions_lock:
            conversations = list(self._sessions.values())
            self._sessions.clear()
        await asyncio.gather(
            *(conversation.close() for conversation in conversations),
            return_exceptions=True,
        )

    async def _discard_startup_agent_greeting(self, conversation) -> None:
        try:
            await self._receive_agent_response(
                conversation,
                timeout_s=self.startup_greeting_timeout_s,
                idle_timeout_s=self.startup_greeting_idle_timeout_s,
            )
        except TimeoutError:
            pass

    async def _receive_agent_response(
        self,
        conversation,
        *,
        timeout_s: float | None = None,
        idle_timeout_s: float | None = None,
    ) -> str:
        agent_responses: list[str] = []
        response_timeout = timeout_s or self.response_timeout_s
        response_idle_timeout = (
            idle_timeout_s
            if idle_timeout_s is not None
            else self.response_idle_timeout_s
        )
        response_deadline = asyncio.get_running_loop().time() + response_timeout
        idle_deadline: float | None = None
        end_events = {
            "conversation_ended",
            "conversation_end",
            "end",
            "done",
        }

        while True:
            now = asyncio.get_running_loop().time()
            if agent_responses and idle_deadline is not None and now >= idle_deadline:
                return " ".join(agent_responses).strip()

            timeout = response_deadline - now
            if agent_responses and idle_deadline is not None:
                timeout = min(timeout, idle_deadline - now)
            if timeout <= 0:
                if agent_responses:
                    return " ".join(agent_responses).strip()
                raise TimeoutError

            try:
                event = await asyncio.wait_for(
                    conversation.next_event(),
                    timeout=timeout,
                )
            except TimeoutError:
                if agent_responses:
                    return " ".join(agent_responses).strip()
                raise
            event_type = event.get("type")

            if event_type == "_connection_closed":
                if agent_responses:
                    return " ".join(agent_responses).strip()
                reason = event.get("reason") or "no agent response was received"
                raise ElevenLabsConversationClosed(
                    f"ElevenLabs closed the conversation: {reason}"
                )

            if event_type in end_events:
                if agent_responses:
                    return " ".join(agent_responses).strip()
                raise ElevenLabsConversationClosed(
                    f"ElevenLabs ended the conversation before an agent response: {event_type}"
                )

            if event_type in {"user_transcript", "user_message"}:
                continue

            if event_type == "agent_response":
                response = (event.get("agent_response_event") or {}).get("agent_response")
                if response:
                    agent_responses.append(response)
                    idle_deadline = asyncio.get_running_loop().time() + response_idle_timeout

            if event_type == "agent_response_correction":
                response = (
                    event.get("agent_response_correction_event") or {}
                ).get("corrected_agent_response")
                if response:
                    agent_responses = [response]
                    idle_deadline = asyncio.get_running_loop().time() + response_idle_timeout

            if event_type == "error":
                raise ElevenLabsAgentError(event.get("message") or "ElevenLabs agent error")


class ElevenLabsConversationSession:
    def __init__(self, service: ElevenLabsAgentService):
        self.service = service
        self.websocket = None
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.send_lock = asyncio.Lock()
        self.reader_task: asyncio.Task | None = None
        self.initialized = False
        self.closed = False

    async def send_user_message(self, messages: List[Message], user_message: str) -> str:
        async with self.lock:
            await self._ensure_connected(messages)
            try:
                await self._drain_stale_events()
                await self._send_json({"type": "user_message", "text": user_message})
                return await self.service._receive_agent_response(self)
            except ConnectionClosed as exc:
                self.closed = True
                reason = exc.reason or "no agent response was received"
                raise ElevenLabsConversationClosed(
                    f"ElevenLabs closed the conversation: {reason}"
                ) from exc

    async def _ensure_connected(self, messages: List[Message]) -> None:
        if self.initialized and not self.closed:
            return

        uri = await self.service._get_signed_url()
        self.websocket = await self.service._connect(uri, {})
        self.closed = False
        self.reader_task = asyncio.create_task(self._reader_loop())

        await self._send_json(self.service._conversation_initiation_payload())
        await self.service._discard_startup_agent_greeting(self)

        self.initialized = True

    async def _drain_stale_events(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except asyncio.QueueEmpty:
                return
            if event.get("type") == "_connection_closed":
                self.closed = True
                reason = event.get("reason") or "no agent response was received"
                raise ElevenLabsConversationClosed(
                    f"ElevenLabs closed the conversation: {reason}"
                )
            if event.get("type") == "error":
                raise ElevenLabsAgentError(event.get("message") or "ElevenLabs agent error")

    async def _reader_loop(self) -> None:
        try:
            while self.websocket is not None:
                raw_message = await self.websocket.recv()
                event = json.loads(raw_message)
                if event.get("type") == "ping":
                    ping_event = event.get("ping_event") or {}
                    await self._send_json(
                        {
                            "type": "pong",
                            "event_id": ping_event.get("event_id"),
                        }
                    )
                    continue
                await self.events.put(event)
        except ConnectionClosed as exc:
            self.closed = True
            await self.events.put(
                {
                    "type": "_connection_closed",
                    "reason": exc.reason,
                }
            )
        except Exception as exc:
            self.closed = True
            await self.events.put(
                {
                    "type": "error",
                    "message": str(exc) or "ElevenLabs websocket reader failed",
                }
            )

    async def _send_json(self, payload: dict) -> None:
        if self.websocket is None:
            raise ElevenLabsConversationClosed("ElevenLabs websocket is not connected")
        async with self.send_lock:
            await self.websocket.send(json.dumps(payload))

    async def next_event(self) -> dict:
        return await self.events.get()

    async def close(self) -> None:
        self.closed = True
        if self.reader_task is not None:
            self.reader_task.cancel()
        if self.websocket is not None:
            await self.websocket.close()
        if self.reader_task is not None:
            try:
                await self.reader_task
            except asyncio.CancelledError:
                pass
