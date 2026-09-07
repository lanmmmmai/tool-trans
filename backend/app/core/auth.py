"""
TEMPORARY STUB — replaced in Phase 9 with real Supabase JWT verification.
`get_current_user_id` keeps the same name/signature so every router written
against it in Phases 2-8 needs no changes when Phase 9 lands.
"""

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def get_current_user_id() -> str:
    return DEV_USER_ID
