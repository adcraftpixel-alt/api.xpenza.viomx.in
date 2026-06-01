from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.api.v1.family.schemas import CreateGroupRequest, InviteMemberRequest, AcceptInviteRequest
from app.api.v1.family.service import FamilyService
from app.utils.response import success

router = APIRouter(tags=["Family"])
service = FamilyService()


@router.post("/groups")
def create_group(
    data: CreateGroupRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    group = service.create_group(db, str(current_user.id), data)
    return success(group, message="Family group created")


@router.get("/groups/me")
def get_my_group(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    group = service.get_my_group(db, str(current_user.id))
    return success(group)


@router.post("/invite")
def invite_member(
    data: InviteMemberRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    member = service.invite_member(db, str(current_user.id), data)
    return success(member, message="Invite sent")


@router.get("/members")
def get_members(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    members = service.get_members(db, str(current_user.id))
    return success(members)


@router.get("/invites/pending")
def get_pending_invites(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    invites = service.get_pending_invites(db, str(current_user.id))
    return success(invites)


@router.post("/invites/accept")
def accept_invite(
    data: AcceptInviteRequest,
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    member = service.accept_invite(db, str(current_user.id), data.group_id)
    return success(member, message="Invite accepted")


@router.get("/expenses")
def get_family_expenses(
    year: int = Query(...),
    month: int = Query(...),
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    data = service.get_family_expenses(db, str(current_user.id), year, month)
    return success(data)


@router.get("/budgets")
def get_shared_budgets(
    current_user=Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    budgets = service.get_shared_budgets(db, str(current_user.id))
    return success(budgets)
