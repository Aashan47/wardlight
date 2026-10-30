"""SMS and USSD webhooks in Africa's Talking's callback format (sandbox: nothing is sent)."""

from __future__ import annotations

from api_helpers import make_settings
from fastapi.testclient import TestClient

from api.main import create_app


def ussd(c, text, session="ATUid_test", phone="+2348000000001"):
    return c.post("/api/ussd", data={"sessionId": session, "serviceCode": "*384*123#", "phoneNumber": phone,
                                     "networkCode": "62120", "text": text})


def test_ussd_flow(fx_client):
    r = ussd(fx_client, "")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert r.text.startswith("CON ") and "sandbox" in r.text.lower()
    assert ussd(fx_client, "1").text.startswith("CON ")
    end = ussd(fx_client, "1*2").text
    assert end.startswith("END ") and "SANDBOX" in end and "Fridge 2-8C" in end
    assert len(end) <= 182
    assert ussd(fx_client, "1*9999").text.startswith("END Code 9999 not found")
    assert ussd(fx_client, "3").text.startswith("END ")
    two = ussd(fx_client, "2")  # no verifier in fixture mode, said plainly
    assert two.text.startswith("END ") and "not available" in two.text and two.headers["x-sandbox"] == "true"


def test_ussd_requires_session(fx_client):
    assert fx_client.post("/api/ussd", data={"text": ""}).status_code == 422


def test_sms_inbound(fx_client):
    r = fx_client.post("/api/sms/inbound", data={"from": "+2348000000001", "to": "12345", "text": "2",
                                                 "date": "x", "id": "m1", "linkId": "l1"})
    j = r.json()
    assert r.status_code == 200 and j["sandbox"] is True and j["sent"] is False
    assert j["to"] == "+2348000000001" and "SANDBOX" in j["reply"] and j["chars"] == len(j["reply"])
    j2 = fx_client.post("/api/sms/inbound", data={"from": "+234", "text": "nonsense"}).json()
    assert "not found" in j2["reply"]
    assert "Send a facility code" in fx_client.post("/api/sms/inbound", data={"from": "+234", "text": ""}).json()["reply"]
    assert fx_client.post("/api/sms/inbound", data={"from": "+234"}).status_code == 422


def test_telephony_rate_limit_is_per_phone(fixture_root):
    c = TestClient(create_app(make_settings(fixtures=fixture_root, rate_telephony=2)))
    assert [ussd(c, "", phone="+1").status_code for _ in range(3)] == [200, 200, 429]
    assert ussd(c, "", phone="+2").status_code == 200
