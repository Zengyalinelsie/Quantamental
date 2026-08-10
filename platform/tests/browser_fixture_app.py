"""Test-only read API used by browser capability checks; never imported at runtime."""

from a_share_platform.api.app import create_app
from tests.market_data_fixtures import build_market_data_fixture
from tests.security_master_fixtures import build_security_master_fixture
from tests.universe_fixtures import build_universe_fixture

app = create_app(
    security_master=build_security_master_fixture(),
    universe_catalog=build_universe_fixture(),
    market_data_catalog=build_market_data_fixture(),
)
