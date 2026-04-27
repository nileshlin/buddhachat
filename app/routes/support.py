from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.database.db import get_db
from app.database.models import User
from app.database.models import SupportIssueStatus as DbSupportIssueStatus
from app.schemas.support import (
    SupportIssueCreate,
    SupportIssueResponse,
    SupportIssueStatus,
    SupportIssueListItem,
    AdminSupportIssueListItem,
)
from app.services.auth import get_current_user, require_admin
from app.services.email_service import email_service
from app.services.support_service import SupportService


router = APIRouter()


@router.post("/issues", response_model=SupportIssueResponse, status_code=201)
async def create_support_issue(
    payload: SupportIssueCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    description = (payload.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    if len(description) > 5000:
        raise HTTPException(status_code=400, detail="Description is too long")

    issue = await SupportService.create_issue(
        db,
        user_id=current_user.id,
        description=description,
        category=(payload.category.strip() if payload.category else None),
        metadata=payload.metadata,
    )

    email_sent = True
    try:
        await email_service.send_support_issue_email(
            support_email=settings.SUPPORT_EMAIL,
            user_email=current_user.email,
            issue_id=issue.id,
            status=issue.status.value,
            description=description,
        )
    except Exception:
        email_sent = False

    return SupportIssueResponse(
        id=issue.id,
        status=SupportIssueStatus(issue.status.value),
        created_at=issue.created_at.isoformat(),
        email_sent=email_sent,
    )


@router.get("/issues/me", response_model=list[SupportIssueListItem])
async def list_my_support_issues(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    issues = await SupportService.list_user_issues(db, user_id=current_user.id)
    return [
        SupportIssueListItem(
            id=issue.id,
            description=issue.description,
            category=issue.category,
            status=SupportIssueStatus(issue.status.value),
            created_at=issue.created_at.isoformat(),
            closed_at=(issue.closed_at.isoformat() if issue.closed_at else None),
        )
        for issue in issues
    ]


@router.post("/issues/{issue_id}/close", response_model=SupportIssueListItem)
async def close_my_support_issue(
    issue_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    issue = await SupportService.get_issue(db, issue_id=issue_id)
    if not issue or issue.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Issue not found")

    issue = await SupportService.close_issue(db, issue_id=issue_id, closed_by_user_id=current_user.id)

    return SupportIssueListItem(
        id=issue.id,
        description=issue.description,
        category=issue.category,
        status=SupportIssueStatus(issue.status.value),
        created_at=issue.created_at.isoformat(),
        closed_at=(issue.closed_at.isoformat() if issue.closed_at else None),
    )


@router.get("/admin/issues", response_model=list[AdminSupportIssueListItem])
async def admin_list_support_issues(
    status: SupportIssueStatus = Query(default=SupportIssueStatus.open),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    db_status = DbSupportIssueStatus.OPEN if status == SupportIssueStatus.open else DbSupportIssueStatus.CLOSED
    issues = await SupportService.list_issues(db, status=db_status, limit=limit, offset=offset)
    items: list[AdminSupportIssueListItem] = []
    for issue in issues:
        items.append(
            AdminSupportIssueListItem(
                id=issue.id,
                user_id=issue.user_id,
                user_email=(issue.user.email if issue.user else ""),
                description=issue.description,
                category=issue.category,
                status=SupportIssueStatus(issue.status.value),
                created_at=issue.created_at.isoformat(),
                closed_at=(issue.closed_at.isoformat() if issue.closed_at else None),
            )
        )
    return items


@router.post("/admin/issues/{issue_id}/close", response_model=SupportIssueListItem)
async def admin_close_support_issue(
    issue_id: int,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    issue = await SupportService.close_issue(db, issue_id=issue_id, closed_by_user_id=_admin.id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    return SupportIssueListItem(
        id=issue.id,
        description=issue.description,
        category=issue.category,
        status=SupportIssueStatus(issue.status.value),
        created_at=issue.created_at.isoformat(),
        closed_at=(issue.closed_at.isoformat() if issue.closed_at else None),
    )
