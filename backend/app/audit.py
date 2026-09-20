from sqlalchemy.orm import Session

from .models import AuditLog, User


def record(db: Session, org_id: int, action: str, entity: str, entity_id: int | None = None,
           actor: User | None = None, **meta) -> None:
    db.add(AuditLog(org_id=org_id, actor_id=actor.id if actor else None,
                    actor_label=actor.email if actor else "system",
                    action=action, entity=entity, entity_id=entity_id, meta=meta))
