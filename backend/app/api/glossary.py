from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.glossary_term import GlossaryTerm

router = APIRouter(prefix="/api/glossary", tags=["glossary"])


class GlossaryTermCreate(BaseModel):
    source_term: str
    target_term: str


class GlossaryTermRead(BaseModel):
    id: str
    source_term: str
    target_term: str

    class Config:
        from_attributes = True


@router.get("", response_model=list[GlossaryTermRead])
def list_glossary_terms(
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    return session.exec(select(GlossaryTerm).where(GlossaryTerm.user_id == user_id)).all()


@router.post("", response_model=GlossaryTermRead, status_code=201)
def create_glossary_term(
    payload: GlossaryTermCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    term = GlossaryTerm(user_id=user_id, **payload.model_dump())
    session.add(term)
    session.commit()
    session.refresh(term)
    return term
