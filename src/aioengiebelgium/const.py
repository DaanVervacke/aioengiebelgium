from enum import Enum, StrEnum
from importlib.metadata import version as _pkg_version

AUTH_BASE_URL = "https://account.engie.be"
PREMISES_BASE_URL = "https://api.engie.be/engie/ms/premises/customer/v1"
PEAKS_BASE_URL = "https://api.engie.be/engie/ms/b2c-energy-insights/v1"
ACCOUNTS_BASE_URL = "https://api.engie.be/engie/ms/accounts/customer/v1"
HAPPY_HOUR_BASE_URL = "https://api.engie.be/engie/ms/energy-insights/customer/v1"
ENERGY_INSIGHTS_V2_BASE_URL = "https://api.engie.be/engie/ms/energy-insights/customer/v2"
BOOLEAN_FEATURE_FLAG_BASE_URL = (
    "https://api.engie.be/engie/ms/feature-flags/customer/v1/boolean-feature-flags/_query"
)
BILLING_BASE_URL = "https://api.engie.be/engie/ms/billing/customer/v1"
BILLING_V2_BASE_URL = "https://api.engie.be/engie/ms/billing/customer/v2"
BUSINESS_AGREEMENTS_BASE_URL = "https://api.engie.be/engie/ms/business-agreements/customer/v1"
EPEX_BASE_URL = "https://api.engie.be/engie/ms/pricing/v1/public/prices/epex"
EV_BASE_URL = "https://api.engie.be/engie/ms/ev/customer/v1"
EV_V2_BASE_URL = "https://api.engie.be/engie/ms/ev/customer/v2"

DEFAULT_CLIENT_ID = "R0PQyUdjO5B2tBaRnltgitVnnUmjGyld"
REDIRECT_URI = "be.engie.smart://login-callback/nl"
OAUTH_SCOPES = "openid profile roles offline_access"
OAUTH_AUDIENCE = "customer"

EPEX_MWH_TO_KWH = 1000.0

DELIVERY_POINT_SUFFIX = "_ID1"

DYNAMIC_ENERGY_PRODUCTS: frozenset[str] = frozenset({"DYNAMIC"})

FEATURE_FLAG_PLATFORM = "android"
FEATURE_FLAG_PLATFORM_VERSION = "16"
FEATURE_FLAG_APP_VERSION = "5.0.0.1168"

_LIB_VERSION = _pkg_version("aioengiebelgium")

USER_AGENT_BROWSER = (
    "Mozilla/5.0 (Linux; Android 10; K) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/142.0.0.0 Mobile Safari/537.36 aioengiebelgium/{_LIB_VERSION}"
)
USER_AGENT_NATIVE = (
    "Dalvik/2.1.0 (Linux; U; Android 16; Pixel 6 Build/BP4A.251205.006)"
    f" aioengiebelgium/{_LIB_VERSION}"
)


class TouSlotCode(StrEnum):
    """Known time-of-use schedule slot codes, stored lowercase.

    The parser drops any direction prefix such as ``S_TOU1_OFFTAKE_`` and maps
    ``HIGH_LOAD_HOURS`` and ``LOW_LOAD_HOURS`` to ``peak`` and ``offpeak``.
    Unknown codes get the same treatment and pass through lowercased.
    """

    PEAK = "peak"
    OFFPEAK = "offpeak"
    SUPEROFFPEAK = "superoffpeak"
    EXCLUSIVE_NIGHT = "exclusive_night"
    DAY = "day"
    TOTAL_HOURS = "total_hours"


class SolarSurplusLevel(StrEnum):
    """Known solar-surplus forecast levels, stored lowercase."""

    NO_DATA = "no_data"
    NO_SURPLUS = "no_surplus"
    MINIMAL_SURPLUS = "minimal_surplus"
    LOW_SURPLUS = "low_surplus"
    HIGH_SURPLUS = "high_surplus"


class SolarInferenceKey(StrEnum):
    """Known solar-surplus forecast inference keys, stored lowercase."""

    ACTUALS = "actuals"
    NO_DATA = "no_data"


class VehicleChargeStatus(StrEnum):
    """Known vehicle charge statuses, stored lowercase. Unknown statuses pass through lowercased."""

    UNPLUGGED = "unplugged"


class VehiclePolicyState(StrEnum):
    """Known vehicle policy states, stored lowercase. Unknown states pass through lowercased."""

    SCHEDULE = "schedule"


class ChargingSessionType(StrEnum):
    """Known charging session types, stored lowercase. Unknown types pass through lowercased."""

    SMART_CHARGING = "smart_charging"
    PUBLIC = "public"


class ChargingSessionStatus(StrEnum):
    """Known session statuses, stored lowercase. Unknown statuses pass through lowercased."""

    ENDED = "ended"
    UNKNOWN = "unknown"


class ChargingSessionSource(StrEnum):
    """Known charging session sources, stored lowercase. Unknown sources pass through lowercased."""

    ENODE = "enode"


class SmartChargeOutcomeState(StrEnum):
    """Known Smart Charge outcomes, stored lowercase. Unknown outcomes pass through lowercased."""

    ON_TARGET = "on_target"
    OFF_TARGET = "off_target"


class ChargeSettingMode(StrEnum):
    """Known charge setting modes, stored lowercase. Unknown modes pass through lowercased."""

    NATIVE = "native"


class EpexGranularity(Enum):
    """Granularity options for EPEX market data, valued in minutes."""

    HOURLY = 60
    QUARTER_HOURLY = 15

    @property
    def wire_value(self) -> str:
        """The granularity string the EPEX endpoint expects."""
        return self.name


class UsageGranularity(StrEnum):
    """Granularity options for the usage-details endpoint."""

    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class MfaMethod(StrEnum):
    """Second-factor channel for the MFA login flow."""

    SMS = "sms"
    EMAIL = "email"


class FeatureFlagKey(StrEnum):
    """Boolean feature flags the API can be queried for."""

    HAPPY_HOURS_SERVICE_ENABLED = "happy-hours-service-enabled"
    SOLAR_SURPLUS_SHOWN_DASHBOARD = "solar-surplus-shown-dashboard"
    TOU_IS_ACTIVE = "tou-is-active"
