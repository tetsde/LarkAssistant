# HiLark Server Tests Package
from .query_claims import ClaimQuerier

# Backward compatibility alias
FactQuerier = ClaimQuerier

__all__ = ["ClaimQuerier", "FactQuerier"]
