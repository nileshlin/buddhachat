from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class SupportIssueStatus(str, Enum):
    open = "open"
    closed = "closed"


class SupportIssueCreate(BaseModel):
    description: str
    category: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class SupportIssueResponse(BaseModel):
    id: int
    status: SupportIssueStatus
    created_at: str
    email_sent: bool


class SupportIssueListItem(BaseModel):
    id: int
    description: str
    category: Optional[str] = None
    status: SupportIssueStatus
    created_at: str
    closed_at: Optional[str] = None


class AdminSupportIssueListItem(SupportIssueListItem):
    user_id: int
    user_email: str
