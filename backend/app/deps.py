from dataclasses import dataclass

from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import ROLE_RANK, Membership, Organization, Role, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     db: Session = Depends(get_db)) -> User:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(creds.credentials, "access")
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return user


@dataclass
class OrgContext:
    user: User
    org: Organization
    role: Role


def org_context(org_id: int = Path(...), user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> OrgContext:
    """Tenant gate. Every /api/orgs/{org_id}/... route depends on this: the caller must be a
    member of the org, otherwise the org is reported as not found (no existence leak)."""
    row = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Organization.id == org_id, Membership.user_id == user.id)
    ).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrgContext(user=user, org=row[0], role=row[1])


def require_role(minimum: Role):
    """RBAC dependency factory: `Depends(require_role(Role.admin))`."""
    def dep(ctx: OrgContext = Depends(org_context)) -> OrgContext:
        if ROLE_RANK[ctx.role] < ROLE_RANK[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Requires {minimum.value} role (you are {ctx.role.value})")
        return ctx
    return dep
