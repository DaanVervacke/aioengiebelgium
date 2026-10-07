EPEX prices
===========

The EPEX day-ahead endpoint is public. It works on a client with no tokens
and no login, and then the request carries no ``Authorization`` header. A
logged-in client can call it too and sends its token.

.. code-block:: python

   import asyncio
   from datetime import UTC, datetime, timedelta

   from aioengiebelgium import EngieBeClient


   async def main() -> None:
       async with EngieBeClient() as client:
           now = datetime.now(UTC)
           prices = await client.async_get_epex_prices(now, now + timedelta(days=1))
           print(prices)


   asyncio.run(main())

Slots and granularity
---------------------

Each :class:`~aioengiebelgium.EpexSlot` is one market-time unit of
day-ahead prices. It carries an aware start and end plus a value in
€/kWh, converted from the API's €/MWh. Slot ends are derived from
consecutive slot starts, not from the requested granularity.

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
