"""RDAP (the modern WHOIS replacement) lookup for an ASN resource —
manual, consultant-triggered only (apps.portal.views.resource_asn_lookup).
Read-only, no credentials, no write: just a convenience to show public
registration data next to a cataloged ASN/Upstream resource. Uses the
public rdap.org bootstrap redirector so we never need to know which
regional registry (LACNIC, ARIN, RIPE...) holds a given ASN.
"""

import httpx

RDAP_AUTNUM_URL = "https://rdap.org/autnum/{asn}"


def _vcard_value(vcard_array, field):
    if not vcard_array or len(vcard_array) < 2:
        return None
    for entry in vcard_array[1]:
        if entry and entry[0] == field:
            return entry[-1]
    return None


def lookup_asn(asn_number: str) -> dict:
    """Raises ValueError for a malformed number, httpx.HTTPError for any
    network/4xx/5xx failure — the view turns both into a user-facing
    message, never a 500.
    """
    digits = "".join(ch for ch in str(asn_number) if ch.isdigit())
    if not digits:
        raise ValueError("Número de ASN inválido.")
    url = RDAP_AUTNUM_URL.format(asn=digits)
    response = httpx.get(url, timeout=10, follow_redirects=True)
    response.raise_for_status()
    data = response.json()

    org_name = None
    for entity in data.get("entities", []):
        org_name = _vcard_value(entity.get("vcardArray"), "fn")
        if org_name:
            break

    registered_on = None
    for event in data.get("events", []):
        if event.get("eventAction") == "registration":
            registered_on = event.get("eventDate")
            break

    return {
        "handle": data.get("handle"),
        "name": data.get("name"),
        "org_name": org_name,
        "country": data.get("country"),
        "status": ", ".join(data.get("status", [])) or None,
        "registered_on": registered_on,
        "source_url": url,
    }
