"""
Constants used by the Smart Oil Gauge integration.

This file contains all string literals, configuration keys, URLs,
default values, and platform declarations so they are defined in one place.

Home Assistant imports this module frequently, so it MUST remain lightweight
(no network I/O, no heavy logic).
"""

# -----------------------------------------------------------------------------
# Basic integration identifiers
# -----------------------------------------------------------------------------

# Domain name used throughout Home Assistant for this integration
DOMAIN = "smart_oil_gauge"

# Human-readable name (optional, but useful for logs / devices)
INTEGRATION_NAME = "Smart Oil Gauge"


# -----------------------------------------------------------------------------
# Config entry keys (stored in entry.data or entry.options)
# -----------------------------------------------------------------------------

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Option: scan interval (seconds between API updates)
CONF_SCAN_INTERVAL = "scan_interval"


# -----------------------------------------------------------------------------
# Default values
# -----------------------------------------------------------------------------

# Default polling interval for tank data.
#
# SmartOilGauge tanks updates once an hour at its most frequent setting
DEFAULT_SCAN_INTERVAL = 3600  # 3600 seconds = 1 hour

# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------

# Login page URL used to fetch nonce + authenticate.
LOGIN_URL = "https://app.smartoilgauge.com/login.php"

# AJAX endpoint for API actions (e.g., get_tanks_list)
AJAX_URL = "https://app.smartoilgauge.com/ajax/main_ajax.php"


# -----------------------------------------------------------------------------
# Platform support (sensor + binary_sensor modules)
# -----------------------------------------------------------------------------

# Home Assistant will forward setup to these platform modules.
# Each entry must correspond to a file:
#   - sensor.py
#   - binary_sensor.py
PLATFORMS = ("sensor", "binary_sensor")
