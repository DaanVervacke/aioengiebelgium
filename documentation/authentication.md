# Authentication

The login is a stateful two-step flow. `async_start_authentication` runs the
credential steps and returns an `AuthFlow` object that awaits your MFA code.
Call `async_submit_mfa` on that flow once you receive the code.

```python
from aioengiebelgium import EngieBeClient, MfaMethod


async def login(client: EngieBeClient) -> None:
    flow = await client.async_start_authentication(
        "user@example.com",
        "password",
        mfa_method=MfaMethod.SMS,
    )
    # Once you receive your MFA code, then:
    await flow.async_submit_mfa("123456")
```

`MfaMethod` selects the second-factor channel. The known values are `SMS` and
`EMAIL`.

A failed code raises `EngieBeMfaError`. Bad credentials or an expired token
raise `EngieBeAuthenticationError`.

## Token rotation

ENGIE rotates the refresh token on every refresh call, and the previous refresh
token becomes invalid immediately. If you pass an `on_token_refresh` callback,
it receives the new `(access_token, refresh_token)` pair whenever the tokens
change. That happens on a manual refresh, on an automatic refresh before
expiry, and on a refresh triggered by a 401.

You must persist every rotated pair durably. If you keep using the old refresh
token after a rotation, the next refresh fails and the user has to log in
again.

Deliveries to the callback are ordered. A pair superseded before delivery is
dropped, so the callback always ends on the newest pair.

## Reusing saved tokens

Pass a stored token pair to the constructor to skip the login entirely:

```python
from aioengiebelgium import EngieBeClient


async def resume(access: str, refresh: str) -> None:
    async with EngieBeClient(
        access_token=access,
        refresh_token=refresh,
        on_token_refresh=persist_tokens,
    ) as client:
        relations = await client.async_get_customer_account_relations()
```

Refreshes are serialized behind a lock, so concurrent requests trigger at most
one refresh call.

## Token state

The access token is a JWT. `access_token_expiry` reads its `exp` claim, and
`is_access_token_expired(now)` takes a caller-supplied aware `now`. The JWT
`sub` claim, exposed as `subject`, is the stable account identifier. Do not
substitute the user's email for it.

## Session ownership

An injected `session` is caller-owned. The client closes only a session it
created itself, so a caller that injects a session keeps responsibility for
closing it.
