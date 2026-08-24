import time

import pytest

from app_core.runtime.cancellation import CancelToken, OperationCancelled


def test_cancel_token_is_idempotent_and_keeps_first_reason():
    token = CancelToken()

    assert token.cancel("user_stop")
    assert not token.cancel("other")
    assert token.is_cancelled()
    assert token.reason == "user_stop"
    with pytest.raises(OperationCancelled, match="user_stop"):
        token.checkpoint()


def test_deadline_cancels_token():
    token = CancelToken.with_timeout(0.01)
    time.sleep(0.02)

    assert token.is_cancelled()
    assert token.reason == "deadline_exceeded"
    assert token.remaining_seconds() == 0.0
