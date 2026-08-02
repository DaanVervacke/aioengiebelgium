# aioengiebelgium

Unofficial asynchronous Python library to interact with
the ENGIE Belgium API.

Requires Python >= 3.14.

## Install

```bash
pip install aioengiebelgium
```

## Usage

```python
import asyncio
import json
from pathlib import Path

from aioengiebelgium import EngieBeClient, MfaMethod

_TOKEN_FILE = Path("tokens.json")


async def persist_tokens(access_token: str, refresh_token: str) -> None:
    # Save the token pair for the next refresh.
    payload = json.dumps({"access": access_token, "refresh": refresh_token})
    await asyncio.to_thread(_TOKEN_FILE.write_text, payload)


async def first_login() -> None:
    # First run: log in with MFA. on_token_refresh saves the tokens.
    async with EngieBeClient(on_token_refresh=persist_tokens) as client:
        flow = await client.async_start_authentication(
            "user@example.com",
            "password",
            mfa_method=MfaMethod.SMS,
        )
        # Once you receive your MFA code, then:
        await flow.async_submit_mfa("123456")

        relations = await client.async_get_customer_account_relations()
        print(relations)


async def next_run() -> None:
    # Later runs: reuse the saved tokens and skip the login entirely.
    raw = await asyncio.to_thread(_TOKEN_FILE.read_text)
    tokens = json.loads(raw)

    async with EngieBeClient(
        access_token=tokens["access"],
        refresh_token=tokens["refresh"],
        on_token_refresh=persist_tokens,
    ) as client:
        contracts = await client.async_get_energy_contracts("1234567890")
        print(contracts)


if _TOKEN_FILE.exists():
    asyncio.run(next_run())
else:
    asyncio.run(first_login())
```

## Development

This project uses [uv](https://docs.astral.sh/uv/) and targets Python 3.14+.

```bash
uv sync
uv run python -m scripts.check
```

## License

MIT, see [LICENSE](LICENSE).
