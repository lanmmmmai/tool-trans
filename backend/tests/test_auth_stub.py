from app.core.auth import DEV_USER_ID, get_current_user_id


def test_get_current_user_id_returns_dev_user():
    assert get_current_user_id() == DEV_USER_ID
    assert isinstance(DEV_USER_ID, str)
    assert len(DEV_USER_ID) > 0
