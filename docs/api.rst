API reference
=============

Client
======

Every constructor argument after ``session`` is keyword-only.

=====================  ==========================================================
Argument               Meaning
=====================  ==========================================================
``session``            Caller-owned ``aiohttp.ClientSession``. The client closes
                       only a session it created itself.
``client_id``          OAuth client id for the Auth0 flow. Defaults to
                       ``DEFAULT_CLIENT_ID``.
``access_token``       Previously stored access token. Skips the login flow.
``refresh_token``      Previously stored refresh token. Rotated on every
                       refresh. On its own it also skips the login flow.
``on_token_refresh``   Async callback that receives every new
                       ``(access_token, refresh_token)`` pair.
``request_timeout``    Per-request timeout in seconds. Defaults to ``30.0``.
=====================  ==========================================================

``async_activate_happy_hour_service`` and ``async_cancel_happy_hour_service``
change the customer's ENGIE service. They were built from the ENGIE Smart
App's API contract and have not been run against a live account. An
:class:`~aioengiebelgium.EngieBeInvalidResponseError` after activation can
still mean the activation worked, so confirm with
``async_get_happy_hour_service_status``.

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

.. autodata:: aioengiebelgium.__version__

Models
======

Response models that hold lists carry ``skipped_entries``, the number of
malformed entries the parser dropped. The count includes entries dropped from
nested lists, such as the business agreements of an account or the registers
of a meter read. A non-zero count means the response is incomplete.

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

.. autoclass:: aioengiebelgium.BudgetBillingPlan
   :members:

.. autoclass:: aioengiebelgium.BudgetBillingPlanContractPeriod
   :members:

.. autoclass:: aioengiebelgium.BudgetBillingPlanDetails
   :members:

.. autoclass:: aioengiebelgium.BudgetBillingPlanLimits
   :members:

.. autoclass:: aioengiebelgium.BudgetBillingPlanProposal
   :members:

.. autoclass:: aioengiebelgium.BudgetBillingPlanProposalFactor
   :members:

.. autoclass:: aioengiebelgium.BusinessAgreement
   :members:

.. autoclass:: aioengiebelgium.ChargeSettingValue
   :members:

.. autoclass:: aioengiebelgium.ChargingSession
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionChargeSettings
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionConsumption
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionDetails
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionsPage
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionsSummary
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionsSummaryEntry
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

.. autoclass:: aioengiebelgium.DepartureTimes
   :members:

.. autoclass:: aioengiebelgium.EanPrices
   :members:

.. autoclass:: aioengiebelgium.ElectricVehicle
   :members:

.. autoclass:: aioengiebelgium.ElectricVehiclesResponse
   :members:

.. autoclass:: aioengiebelgium.ElectricityUsage
   :members:

.. autoclass:: aioengiebelgium.EnergyContract
   :members:

.. autoclass:: aioengiebelgium.EnergyContractsResponse
   :members:

.. autoclass:: aioengiebelgium.EnergyCostPair
   :members:

.. autoclass:: aioengiebelgium.EnergyScore
   :members:

.. autoclass:: aioengiebelgium.EnergyScoreActions
   :members:

.. autoclass:: aioengiebelgium.EnergyScoreCriteria
   :members:

.. autoclass:: aioengiebelgium.EnergyScoreDataAvailability
   :members:

.. autoclass:: aioengiebelgium.EnergyScoreDetails
   :members:

.. autoclass:: aioengiebelgium.EnergyScoreQuestionAnswer
   :members:

.. autoclass:: aioengiebelgium.EpexPayload
   :members:

.. autoclass:: aioengiebelgium.EpexSlot
   :members:

.. autoclass:: aioengiebelgium.EvService
   :members:

.. autoclass:: aioengiebelgium.EvServiceInfo
   :members:

.. autoclass:: aioengiebelgium.FeatureFlag
   :members:

.. autoclass:: aioengiebelgium.FinancialTransaction
   :members:

.. autoclass:: aioengiebelgium.GasUsage
   :members:

.. autoclass:: aioengiebelgium.HappyHourComparison
   :members:

.. autoclass:: aioengiebelgium.HappyHourEligibility
   :members:

.. autoclass:: aioengiebelgium.HappyHourEvent
   :members:

.. autoclass:: aioengiebelgium.HappyHourMonthData
   :members:

.. autoclass:: aioengiebelgium.HappyHourMonthReport
   :members:

.. autoclass:: aioengiebelgium.HappyHourServiceStatus
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

.. autoclass:: aioengiebelgium.SmartChargeOutcome
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

.. autoclass:: aioengiebelgium.VehicleCapabilities
   :members:

.. autoclass:: aioengiebelgium.VehicleChargeSettings
   :members:

.. autoclass:: aioengiebelgium.VehicleChargeState
   :members:

Enums
=====

.. autoclass:: aioengiebelgium.ChargeSettingMode
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionSource
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionStatus
   :members:

.. autoclass:: aioengiebelgium.ChargingSessionType
   :members:

.. autoclass:: aioengiebelgium.EpexGranularity
   :members:

.. autoclass:: aioengiebelgium.FeatureFlagKey
   :members:

.. autoclass:: aioengiebelgium.MfaMethod
   :members:

.. autoclass:: aioengiebelgium.SmartChargeOutcomeState
   :members:

.. autoclass:: aioengiebelgium.SolarInferenceKey
   :members:

.. autoclass:: aioengiebelgium.SolarSurplusLevel
   :members:

.. autoclass:: aioengiebelgium.TouSlotCode
   :members:

.. autoclass:: aioengiebelgium.UsageGranularity
   :members:

.. autoclass:: aioengiebelgium.VehicleChargeStatus
   :members:

.. autoclass:: aioengiebelgium.VehiclePolicyState
   :members:

Exceptions
==========

Client errors derive from :class:`~aioengiebelgium.EngieBeError`. Catch a
subclass before its parent. Invalid arguments raise ``ValueError`` before any
request is sent. Examples are a business agreement number that is not all
digits, a month outside 1-12, a year outside 2000-2100, a start date after
the end date and a datetime without a timezone. Spaces in a business
agreement or customer account number are removed before the check.
``async_get_meter_reads`` needs both dates or neither, and rejects
``latest=True`` combined with a date range.

.. autoclass:: aioengiebelgium.EngieBeAuthenticationError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeClientClosedError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeCommunicationError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeEpexNotPublishedError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeInvalidResponseError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeMfaError
   :members:
   :show-inheritance:

.. autoclass:: aioengiebelgium.EngieBeTimeoutError
   :members:
   :show-inheritance:

Helpers
=======

.. autofunction:: aioengiebelgium.bare_ean

.. autofunction:: aioengiebelgium.ean_with_delivery_point_suffix
