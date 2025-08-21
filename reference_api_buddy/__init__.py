"""Reference API Buddy - HTTP Caching Proxy for Development.

A Python HTTP-to-HTTPS caching proxy module designed for reference APIs where
the data is non-secure and not changing frequently (ConceptNet, DBpedia, Wikidata, etc).
"""

from reference_api_buddy.cache.engine import CacheEngine
from reference_api_buddy.core.proxy import CachingProxy, SecurityError
from reference_api_buddy.security.manager import SecurityManager
from reference_api_buddy.throttling.manager import ThrottleManager

__version__ = "0.2.0"
__author__ = "Reference API Buddy Team"
__email__ = "contact@example.com"

__all__ = [
    "CachingProxy",
    "SecurityError",
    "SecurityManager",
    "CacheEngine",
    "ThrottleManager",
]
