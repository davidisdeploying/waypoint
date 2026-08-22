"""Compatibility view over the canonical certification spine registry.

New code should call :mod:`lib.certification_spines` directly.  This mapping remains so
older imports and tests keep working while the data itself has one owner.
"""
from lib import certification_spines


CERT_DOMAINS = {
    certification["id"]: certification_spines.projected_domains(certification["id"])
    for certification in certification_spines.list_spines()
    if certification["scope_status"] == "domain_scaffold"
}
