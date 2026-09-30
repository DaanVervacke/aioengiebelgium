"""The public import path re-exports exactly the submodule symbols."""

import inspect
from datetime import UTC, datetime

import pytest

import aioengiebelgium
from aioengiebelgium import _auth, client, const, exceptions, models

_SOURCE_MODULES = (_auth, client, const, exceptions, models)


def test_all_reexports_are_identity_exports() -> None:
    """Every ``__all__`` entry is the very object from its source submodule."""
    for name in aioengiebelgium.__all__:
        if name == "__version__":
            continue
        obj = getattr(aioengiebelgium, name)
        assert any(getattr(module, name, None) is obj for module in _SOURCE_MODULES), (
            f"{name} is not an identity re-export"
        )


def test_all_matches_module_namespace_minus_submodules() -> None:
    """``__all__`` is exactly the public namespace, with submodules removed."""
    submodules = {name for name, value in vars(aioengiebelgium).items() if inspect.ismodule(value)}
    expected = {name for name in vars(aioengiebelgium) if not name.startswith("_")}
    expected.add("__version__")
    assert set(aioengiebelgium.__all__) == expected - submodules


async def test_behavior_call_through_package_path() -> None:
    """One real behavior call through the package path, not a submodule path."""
    pkg_client = aioengiebelgium.EngieBeClient()
    assert pkg_client.is_access_token_expired(datetime.now(UTC)) is False
    await pkg_client.close()
    with pytest.raises(aioengiebelgium.EngieBeClientClosedError):
        await pkg_client.async_get_epex_prices(
            datetime(2026, 5, 3, 22, 0, tzinfo=UTC),
            datetime(2026, 5, 4, 22, 0, tzinfo=UTC),
        )
