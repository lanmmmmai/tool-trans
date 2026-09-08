from uuid import uuid4

from sqlmodel import Field, SQLModel


class GlossaryTerm(SQLModel, table=True):
    __tablename__ = "glossary_terms"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    source_term: str
    target_term: str
