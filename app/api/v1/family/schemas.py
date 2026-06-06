from typing import Optional, List
from pydantic import BaseModel


class CreateGroupRequest(BaseModel):
    name: str
    contribution: Optional[float] = None  # creator's initial contribution


class InviteMemberRequest(BaseModel):
    phone: str
    name: Optional[str] = None


class AcceptInviteRequest(BaseModel):
    group_id: str


class SetContributionRequest(BaseModel):
    amount: float


class MemberResponse(BaseModel):
    id: str
    phone: str
    name: Optional[str]
    role: str
    status: str
    user_id: Optional[str]
    contribution: float = 0


class GroupResponse(BaseModel):
    id: str
    name: str
    created_by: str
    members: List[MemberResponse]
