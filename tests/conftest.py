"""Shared test setup: API tests run as a logged-in admin unless they test logging in itself."""
from uuid import uuid4

import pytest

from athena.core.models import User

ADMIN = User(id=uuid4(), email="admin@example.com", display_name="Admin", password_hash="-", role="admin",
             is_active=True, must_change_password=False)


@pytest.fixture(autouse=True)
def logged_in_admin(request):
    """Every route needs an account since F2; most tests are about something else, so they get an admin.

    Mark a test (or module) with ``@pytest.mark.real_auth`` to go through the real session cookie.
    """
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    from athena.api.auth import active_user, current_user
    from athena.api.main import app
    app.dependency_overrides[current_user] = lambda: ADMIN
    app.dependency_overrides[active_user] = lambda: ADMIN
    yield
    app.dependency_overrides.pop(current_user, None)
    app.dependency_overrides.pop(active_user, None)


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: use real sessions instead of the logged-in admin")
