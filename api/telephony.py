"""SMS and USSD lookup in Africa's Talking's callback formats. SANDBOX: nothing is sent from here.

USSD (Africa's Talking USSD API): the gateway POSTs application/x-www-form-urlencoded fields sessionId,
serviceCode, phoneNumber, networkCode and text, where text is every input of the session so far joined by '*'
('' on the first request). The reply is text/plain beginning "CON " (the session continues) or "END " (it closes).

Inbound SMS (Africa's Talking incoming-message callback): form fields from, to, text, date, id, linkId. The gateway
ignores the HTTP body; a reply is normally sent with the SMS API, which this build does NOT call. The endpoint
returns the reply it would send, marked sandbox and sent: false.

Facility code: the number on the facility sheet (`facility.code`), or the registry id.
"""

from __future__ import annotations

from urllib.parse import parse_qs

SANDBOX_TAG = "SANDBOX"
USSD_MAX = 182  # characters a USSD screen shows


def parse_form(body: bytes) -> dict[str, str]:
    q = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {k: v[-1] for k, v in q.items()}


def _pct(x) -> str:
    return "n/a" if x is None else f"{round(x * 100)}%"


def _short_fix(info: dict) -> str:
    cat = info.get("fix_category")
    short = {"i": "PQS ice-lined fridge on grid", "ii": "PQS solar fridge", "iii": "PQS solar fridge + clinic solar"}
    label = short.get(cat) or (info.get("fix_label") or "no fix listed")
    price = info.get("capex_ngn")
    p = f", N{price / 1e6:.2f}m" if price else ""
    return f"Fix ({cat}): {label}{p}" if cat else f"Fix: {label}{p}"


def facility_lines(info: dict) -> str:
    name = info["name"] if len(info["name"]) <= 28 else info["name"][:27] + "."
    head = f"{info['code']} {name}"
    if not info.get("has_result"):
        return f"{head}\nNo figure: {str(info.get('reason') or 'no engine result').split(';')[0][:70]}"
    fix = _short_fix(info)
    if info.get("uptime_today") is None:
        up = f"Fridge 2-8C: grid unknown; {_pct(info.get('uptime_with_system'))} of days with fix"
    else:
        up = f"Fridge 2-8C: {_pct(info['uptime_today'])} of days now, {_pct(info.get('uptime_with_system'))} with fix"
    return f"{head}\n{fix}\n{up}"


def sms_reply(store, text: str) -> str:
    code = (text or "").strip().split()[0] if (text or "").strip() else ""
    if code.upper() in ("WL", "WARDLIGHT") and len((text or "").split()) > 1:
        code = text.split()[1]
    if not code:
        return f"Send a facility code, e.g. 12 (the number on the facility sheet). {SANDBOX_TAG}"
    info = store.lookup_short(code)
    if info is None:
        return f"Code {code[:20]} not found. Check the number on the facility sheet. {SANDBOX_TAG}"
    return f"{facility_lines(info)}\n{SANDBOX_TAG}"


def _fit(s: str) -> str:
    return s if len(s) <= USSD_MAX else s[: USSD_MAX - 1] + "."


def ussd_reply(store, text: str, verifier=None) -> str:
    """Menu: 1 look up a facility; 2 answer the clinic questions (verifier, live data only); 3 about."""
    parts = [p.strip() for p in (text or "").split("*")] if text else []
    if not parts:
        return _fit("CON Wardlight (sandbox)\n1. Facility fridge and fix\n2. Answer clinic questions\n3. About")
    if parts[0] == "1":
        if len(parts) == 1 or not parts[1]:
            return "CON Enter the facility code (the number on the facility sheet):"
        info = store.lookup_short(parts[1])
        if info is None:
            return _fit(f"END Code {parts[1][:20]} not found. {SANDBOX_TAG}")
        return _fit(f"END {facility_lines(info)}\n{SANDBOX_TAG}")
    if parts[0] == "2":
        if verifier is None:
            return _fit(f"END Clinic questions are not available here. {SANDBOX_TAG}")
        if len(parts) == 1 or not parts[1]:
            return "CON Enter your facility code:"
        info = store.lookup_short(parts[1])
        if info is None:
            return _fit(f"END Code {parts[1][:20]} not found. {SANDBOX_TAG}")
        try:
            out = verifier(info["id"], "*".join(parts[2:]))
        except Exception as e:  # noqa: BLE001 - a verifier failure ends the session politely
            return _fit(f"END Sorry, the questions could not run ({type(e).__name__}). {SANDBOX_TAG}")
        return _fit(out)
    if parts[0] == "3":
        return _fit("END Wardlight estimates the share of days a clinic's vaccine fridge stays at 2-8C, from NERC "
                    f"feeder promises (modelled, not measured). {SANDBOX_TAG}")
    # a bare code goes straight to the lookup
    info = store.lookup_short(parts[0])
    if info is not None:
        return _fit(f"END {facility_lines(info)}\n{SANDBOX_TAG}")
    return _fit(f"END Choose 1, 2 or 3. {SANDBOX_TAG}")
