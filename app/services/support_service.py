from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import selectinload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SupportIssue, SupportIssueStatus


class SupportService:
    @staticmethod
    async def create_issue(
        db: AsyncSession,
        user_id: int,
        description: str,
        category: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> SupportIssue:
        issue = SupportIssue(
            user_id=user_id,
            description=description,
            category=category,
            meta=metadata,
            status=SupportIssueStatus.OPEN,
        )
        db.add(issue)
        await db.commit()
        await db.refresh(issue)
        return issue

    @staticmethod
    async def list_user_issues(db: AsyncSession, user_id: int) -> list[SupportIssue]:
        stmt = (
            select(SupportIssue)
            .where(SupportIssue.user_id == user_id)
            .order_by(SupportIssue.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_issue(db: AsyncSession, issue_id: int) -> Optional[SupportIssue]:
        stmt = select(SupportIssue).where(SupportIssue.id == issue_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_issues(
        db: AsyncSession,
        status: Optional[SupportIssueStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SupportIssue]:
        stmt = select(SupportIssue).options(selectinload(SupportIssue.user)).order_by(SupportIssue.created_at.desc())
        if status is not None:
            stmt = stmt.where(SupportIssue.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def close_issue(db: AsyncSession, issue_id: int, closed_by_user_id: int) -> Optional[SupportIssue]:
        stmt = select(SupportIssue).where(SupportIssue.id == issue_id)
        result = await db.execute(stmt)
        issue = result.scalar_one_or_none()
        if not issue:
            return None

        issue.status = SupportIssueStatus.CLOSED
        issue.closed_at = datetime.utcnow()
        issue.closed_by_user_id = closed_by_user_id

        await db.commit()
        await db.refresh(issue)
        return issue
