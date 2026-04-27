from __future__ import annotations

import asyncio
import re
from typing import List, Optional

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config.settings import settings
from app.database.models import Message


class ScriptGenerationOutput(BaseModel):
    name: str
    script: List[str]
    music_tags: List[str]


class ScriptMetaOutput(BaseModel):
    name: str
    music_tags: List[str]


class OpenAIService:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL

    @staticmethod
    def _is_retryable_openai_error(exc: Exception) -> bool:
        retryable_types: tuple[type[BaseException], ...] = tuple(
            t
            for t in (
                getattr(openai, "RateLimitError", None),
                getattr(openai, "APIConnectionError", None),
                getattr(openai, "APITimeoutError", None),
                getattr(openai, "InternalServerError", None),
                getattr(openai, "APIStatusError", None),
            )
            if isinstance(t, type)
        )
        if retryable_types and isinstance(exc, retryable_types):
            status_code = getattr(exc, "status_code", None)
            if status_code is None:
                return True
            return int(status_code) >= 500 or int(status_code) == 429
        return False

    async def _with_retries(self, fn, *, attempts: int = 3, base_delay_s: float = 0.6):
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await fn()
            except Exception as exc:
                last_exc = exc
                if attempt >= attempts or not self._is_retryable_openai_error(exc):
                    raise
                await asyncio.sleep(base_delay_s * (2 ** (attempt - 1)))
        if last_exc:
            raise last_exc
        raise RuntimeError("Retry loop exited unexpectedly")

    async def generate_agent_response(self, messages: List[Message]) -> str:
        user_turns = sum(1 for msg in messages if msg.role.value == "user")
        agent_turns = sum(1 for msg in messages if msg.role.value == "agent")

        system_instruction = (
            "You are a calm, attentive meditation preparation assistant.\n"
            "Your job is to ask short, natural follow-up questions to understand the user's situation, "
            "so we can generate a personalized meditation audio based on this conversation.\n\n"
            "Conversation goals (gather gently, one at a time):\n"
            "- Current state (busy mind, anxiety, sadness, fatigue, pain, stress, etc.)\n"
            "- What they want to feel after the meditation (goal/intention)\n"
            "Rules:\n"
            "1) Ask ONLY ONE question per response.\n"
            "2) Keep it 1-2 sentences maximum.\n"
            "3) Be warm and validating; do not teach, advise, or explain techniques.\n"
            "4) Do NOT generate any meditation script.\n"
            "5) Do NOT be repetitive; build on what the user just said.\n\n"
            "When you have enough information (usually after 3-4 user messages), respond with a brief confirmation "
            "that matches the user's situation (1-2 sentences) and do NOT ask another question.\n\n"
            f"Meta: So far there are {user_turns} user messages and {agent_turns} agent messages.\n"
            "If the user says 'create meditation' or similar, start by asking about their current mental/emotional state.\n"
        )

        formatted_messages = [{"role": "system", "content": system_instruction}]

        for msg in messages:
            formatted_messages.append(
                {
                    "role": "assistant" if msg.role.value == "agent" else "user",
                    "content": msg.content,
                }
            )

        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=formatted_messages,
            max_tokens=150,
        )

        content = resp.choices[0].message.content or ""
        return content.strip()

    async def summarize_conversation(self, messages: List[Message]) -> str:
        if not messages:
            return "General relaxing meditation"

        convo_text = "\n".join([f"{msg.role.value}: {msg.content}" for msg in messages])

        prompt = f"""Summarize this meditation preparation conversation into a 1-2 sentence core intent.
        Focus strictly on the user's emotional state, goals, or problems.
        Conversation:
        {convo_text}"""

        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
        )
        return (resp.choices[0].message.content or "").strip()

    @staticmethod
    def _count_words(text: str) -> int:
        if not text:
            return 0
        if re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", text):
            return -1
        return len([w for w in re.split(r"\s+", text.strip()) if w])

    @staticmethod
    def _strip_wrapping_quotes(text: str) -> str:
        t = text.strip()
        if len(t) >= 2 and ((t[0] == t[-1] == '"') or (t[0] == t[-1] == "'")):
            return t[1:-1].strip()
        return t

    @staticmethod
    def _normalize_block(text: str) -> str:
        t = OpenAIService._strip_wrapping_quotes(text)
        t = re.sub(r"\n{3,}", "\n\n", t.strip())
        return t

    async def _generate_script_meta(self, summary: str, language: str) -> ScriptMetaOutput:
        prompt = (
            "Create a short, catchy meditation title and 3-4 music tags.\n"
            f"Language: {language}\n"
            f"Context summary: {summary}\n\n"
            "Rules:\n"
            "- Title must be 2-5 words.\n"
            "- music_tags must be 3 or 4 short lowercase tags.\n"
        )
        async def _call():
            return await self.client.beta.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful meditation product copywriter."},
                    {"role": "user", "content": prompt},
                ],
                response_format=ScriptMetaOutput,
                max_tokens=200,
            )

        resp = await self._with_retries(_call, attempts=3)
        parsed = resp.choices[0].message.parsed
        tags = [str(t).strip().lower() for t in (parsed.music_tags or []) if str(t).strip()]
        tags = tags[:4]
        if len(tags) < 3:
            tags.extend(["relaxation"] * (3 - len(tags)))
        return ScriptMetaOutput(name=(parsed.name or "").strip() or "Relax and Reset", music_tags=tags)

    async def _generate_script_block(
        self,
        *,
        summary: str,
        language: str,
        block_index: int,
        block_description: str,
        target_words: int,
        prev_block_tail: Optional[str],
        max_tokens: int,
    ) -> str:
        lower = max(60, int(target_words * 0.9))
        upper = int(target_words * 1.1)
        transition = (
            f"\n\nPrevious block ending to transition from (do not quote it): {prev_block_tail}\n"
            if prev_block_tail
            else ""
        )
        user_prompt = (
            f"Write Block {block_index} of a 5-block spoken meditation script.\n"
            f"Language: {language}\n"
            f"Context summary: {summary}\n"
            f"Block focus: {block_description}\n"
            f"Target length: {target_words} words (acceptable range: {lower}-{upper}).\n"
            "Style:\n"
            "- Warm, calm, and natural spoken narration.\n"
            "- Use short sentences and occasional line breaks for breath.\n"
            "- No headings, no labels like 'Block 1', no stage directions like [pause].\n"
            "- Output ONLY the block text.\n"
            f"{transition}"
        )
        async def _call(tokens: int, temp: float):
            return await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You write meditation narration for a guided audio experience."},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temp,
                max_tokens=tokens,
            )

        resp = await self._with_retries(lambda: _call(max_tokens, 0.7), attempts=3)
        content = self._normalize_block(resp.choices[0].message.content or "")
        if resp.choices and resp.choices[0].finish_reason == "length":
            bumped = min(int(max_tokens * 1.5), 1400)
            resp = await self._with_retries(lambda: _call(bumped, 0.5), attempts=2, base_delay_s=0.8)
            content = self._normalize_block(resp.choices[0].message.content or "")
        wc = self._count_words(content)

        if wc != -1 and (wc < int(lower * 0.8) or wc > int(upper * 1.2)):
            rewrite_prompt = (
                f"Rewrite the meditation text below to be {lower}-{upper} words.\n"
                f"Language: {language}\n"
                "Keep the same meaning and tone.\n"
                "Rules:\n"
                "- Output ONLY the rewritten block text.\n"
                "- No headings, no stage directions.\n\n"
                f"Text:\n{content}"
            )
            resp2 = await self._with_retries(
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You revise meditation narration for length and flow."},
                        {"role": "user", "content": rewrite_prompt},
                    ],
                    temperature=0.4,
                    max_tokens=max_tokens,
                ),
                attempts=3,
            )
            content = self._normalize_block(resp2.choices[0].message.content or "")

        return content

    async def generate_meditation_script(self, summary: str, language: str = "English") -> ScriptGenerationOutput:
        summary_clean = (summary or "").strip()
        language_clean = (language or "English").strip() or "English"

        meta = await self._generate_script_meta(summary_clean, language_clean)

        blocks = [
            (1, "Introduction and settling down.", 180, 600),
            (2, "Deepening focus and breath work.", 300, 900),
            (3, "Core theme exploration.", 180, 600),
            (4, "Integration and silence preparation.", 240, 750),
            (5, "Gentle awakening and conclusion.", 240, 750),
        ]

        script_blocks: List[str] = []
        prev_tail: Optional[str] = None
        for idx, desc, target_words, max_tokens in blocks:
            block_text = await self._generate_script_block(
                summary=summary_clean,
                language=language_clean,
                block_index=idx,
                block_description=desc,
                target_words=target_words,
                prev_block_tail=prev_tail,
                max_tokens=max_tokens,
            )
            script_blocks.append(block_text)

            tail_words = re.split(r"\s+", block_text.strip())
            prev_tail = " ".join(tail_words[-40:]).strip() if tail_words else None

            # Small delay to reduce burst rate if workers scale up.
            await asyncio.sleep(0.05)

        return ScriptGenerationOutput(name=meta.name, script=script_blocks, music_tags=meta.music_tags)
