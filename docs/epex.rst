EPEX prices
===========

The EPEX day-ahead endpoint rejects a call without a valid access token
with a 401. The client omits the ``Authorization`` header when it holds no
token, so a tokenless call surfaces that 401 as
:class:`~aioengiebelgium.EngieBeAuthenticationError`. A logged-in client
sends its token and gets the prices.

The example loads the token pair stored by the :doc:`quickstart` example.

.. code-block:: python

   import asyncio
   import json
   from datetime import UTC, datetime, timedelta
   from pathlib import Path

   from aioengiebelgium import EngieBeClient

   _TOKEN_FILE = Path("tokens.json")


   async def main() -> None:
       stored = json.loads(_TOKEN_FILE.read_text())
       async with EngieBeClient(
           access_token=stored["access"],
           refresh_token=stored["refresh"],
       ) as client:
           now = datetime.now(UTC)
           prices = await client.async_get_epex_prices(now, now + timedelta(days=1))
           print(prices)


   asyncio.run(main())

Slots and granularity
---------------------

Each :class:`~aioengiebelgium.EpexSlot` is one market-time unit of
day-ahead prices. It carries an aware start and end plus a value in
€/kWh, converted from the API's €/MWh. A slot ends at the next slot's
start, capped at the most common spacing between slot starts. A response
with a single slot falls back to the requested granularity. Slots with a
duplicate start time are dropped, and each dropped duplicate counts in
``skipped_entries``.

:class:`~aioengiebelgium.EpexGranularity` selects the market-time-unit
length:

==================  ===============
Value               Meaning
==================  ===============
``HOURLY``          60-minute slots
``QUARTER_HOURLY``  15-minute slots
==================  ===============

Publication window
------------------

Day-ahead prices are published in the afternoon for the following day.
Requesting a window whose prices have not been published yet raises
:class:`~aioengiebelgium.EngieBeEpexNotPublishedError`. Retry later.
