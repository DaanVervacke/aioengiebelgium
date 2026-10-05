API reference
=============

Client
======

.. autoclass:: aioengiebelgium.EngieBeClient
   :members:
   :special-members: __init__

Authentication flow
===================

.. autoclass:: aioengiebelgium.AuthFlow
   :members:

Constants
=========

.. autodata:: aioengiebelgium.DEFAULT_CLIENT_ID

Models
======

.. autoclass:: aioengiebelgium.AccountBalance
   :members:

.. autoclass:: aioengiebelgium.AccountRelation
   :members:

.. autoclass:: aioengiebelgium.BillingDetails
   :members:

.. autoclass:: aioengiebelgium.BillingOverview
   :members:

.. autoclass:: aioengiebelgium.BillingPeriodUsage
   :members:

.. autoclass:: aioengiebelgium.BusinessAgreement
   :members:

.. autoclass:: aioengiebelgium.ConsumptionAddress
   :members:

.. autoclass:: aioengiebelgium.ContractInfo
   :members:

.. autoclass:: aioengiebelgium.CustomerAccount
   :members:

.. autoclass:: aioengiebelgium.CustomerAccountRelations
   :members:

.. autoclass:: aioengiebelgium.DataAvailability
   :members:

.. autoclass:: aioengiebelgium.EanPrices
   :members:

.. autoclass:: aioengiebelgium.ElectricityUsage
   :members:

.. autoclass:: aioengiebelgium.EnergyContract
   :members:

.. autoclass:: aioengiebelgium.EnergyContractsResponse
   :members:

.. autoclass:: aioengiebelgium.EnergyCostPair
   :members:

.. autoclass:: aioengiebelgium.EpexPayload
   :members:

.. autoclass:: aioengiebelgium.EpexSlot
   :members:

.. autoclass:: aioengiebelgium.FeatureFlag
   :members:

.. autoclass:: aioengiebelgium.FinancialTransaction
   :members:

.. autoclass:: aioengiebelgium.GasUsage
   :members:

.. autoclass:: aioengiebelgium.HappyHourComparison
   :members:

.. autoclass:: aioengiebelgium.HappyHourEvent
   :members:

.. autoclass:: aioengiebelgium.HappyHourMonthData
   :members:

.. autoclass:: aioengiebelgium.HappyHourMonthReport
   :members:

.. autoclass:: aioengiebelgium.HappyHourWindow
   :members:

.. autoclass:: aioengiebelgium.MeasuredDataWindow
   :members:

.. autoclass:: aioengiebelgium.MeteringConfiguration
   :members:

.. autoclass:: aioengiebelgium.MeteringDataSource
   :members:

.. autoclass:: aioengiebelgium.MeteringDataSources
   :members:

.. autoclass:: aioengiebelgium.MeteringServicePoint
   :members:

.. autoclass:: aioengiebelgium.MeterRead
   :members:

.. autoclass:: aioengiebelgium.MeterReadsResponse
   :members:

.. autoclass:: aioengiebelgium.MeterRegisterRead
   :members:

.. autoclass:: aioengiebelgium.MonthReportHistoryEntry
   :members:

.. autoclass:: aioengiebelgium.MonthlyBilledBudget
   :members:

.. autoclass:: aioengiebelgium.MonthlyPeaks
   :members:

.. autoclass:: aioengiebelgium.PaymentSlice
   :members:

.. autoclass:: aioengiebelgium.Peak
   :members:

.. autoclass:: aioengiebelgium.PricePeriod
   :members:

.. autoclass:: aioengiebelgium.PriceSlot
   :members:

.. autoclass:: aioengiebelgium.PricesResponse
   :members:

.. autoclass:: aioengiebelgium.ProductConfiguration
   :members:

.. autoclass:: aioengiebelgium.ServicePoint
   :members:

.. autoclass:: aioengiebelgium.ServicePointInstallation
   :members:

.. autoclass:: aioengiebelgium.ServicePointMarketDetails
   :members:

.. autoclass:: aioengiebelgium.ServicePointsResponse
   :members:

.. autoclass:: aioengiebelgium.SimulatedCost
   :members:

.. autoclass:: aioengiebelgium.SimulatedCostFlow
   :members:

.. autoclass:: aioengiebelgium.SimulatedEnergy
   :members:

.. autoclass:: aioengiebelgium.SimulatedEnergyFlow
   :members:

.. autoclass:: aioengiebelgium.SolarSurplusDay
   :members:

.. autoclass:: aioengiebelgium.SolarSurplusForecasts
   :members:

.. autoclass:: aioengiebelgium.SolarSurplusSlot
   :members:

.. autoclass:: aioengiebelgium.TouCombinedDirectionSchedule
   :members:

.. autoclass:: aioengiebelgium.TouCombinedSchedule
   :members:

.. autoclass:: aioengiebelgium.TouCombinedSlot
   :members:

.. autoclass:: aioengiebelgium.TouDirectionSchedule
   :members:

.. autoclass:: aioengiebelgium.TouGridMeterSchedule
   :members:

.. autoclass:: aioengiebelgium.TouSchedule
   :members:

.. autoclass:: aioengiebelgium.TouScheduleItem
   :members:

.. autoclass:: aioengiebelgium.TouSchedulesResponse
   :members:

.. autoclass:: aioengiebelgium.TouSlot
   :members:

.. autoclass:: aioengiebelgium.UsageDetailsResponse
   :members:

.. autoclass:: aioengiebelgium.UsageDirectionBreakdown
   :members:

.. autoclass:: aioengiebelgium.UsageElectricityBreakdown
   :members:

.. autoclass:: aioengiebelgium.UsageItem
   :members:

.. autoclass:: aioengiebelgium.UsageTouCrossPart
   :members:

.. autoclass:: aioengiebelgium.UsageTouPart
   :members:

Enums
=====

.. autoclass:: aioengiebelgium.EpexGranularity
   :members:

.. autoclass:: aioengiebelgium.FeatureFlagKey
   :members:

.. autoclass:: aioengiebelgium.MfaMethod
   :members:

.. autoclass:: aioengiebelgium.SolarInferenceKey
   :members:

.. autoclass:: aioengiebelgium.SolarSurplusLevel
   :members:

.. autoclass:: aioengiebelgium.TouSlotCode
   :members:

.. autoclass:: aioengiebelgium.UsageGranularity
   :members:

Exceptions
==========

.. autoclass:: aioengiebelgium.EngieBeAuthenticationError
   :members:

.. autoclass:: aioengiebelgium.EngieBeClientClosedError
   :members:

.. autoclass:: aioengiebelgium.EngieBeCommunicationError
   :members:

.. autoclass:: aioengiebelgium.EngieBeEpexNotPublishedError
   :members:

.. autoclass:: aioengiebelgium.EngieBeError
   :members:

.. autoclass:: aioengiebelgium.EngieBeInvalidResponseError
   :members:

.. autoclass:: aioengiebelgium.EngieBeMfaError
   :members:

.. autoclass:: aioengiebelgium.EngieBeTimeoutError
   :members:

Helpers
=======

.. autofunction:: aioengiebelgium.bare_ean

.. autofunction:: aioengiebelgium.ean_with_delivery_point_suffix
