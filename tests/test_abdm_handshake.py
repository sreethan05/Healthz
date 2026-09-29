"""ABDM handshake tests: mock default + sandbox path with stubbed HTTP (offline-safe)."""
import backend.abdm as abdm


class _Resp:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_mock_mode_without_credentials(monkeypatch):
    monkeypatch.setattr(abdm, "CLIENT_ID", "")
    monkeypatch.setattr(abdm, "CLIENT_SECRET", "")
    assert abdm.mode() == "mock"
    s = abdm.create_session()
    assert s["ok"] is False and "ABDM_CLIENT_ID" in s["reason"]
    art = abdm.consent_artefact("a@abdm", "hiu", "hip", "OPD", ["Prescription"])
    assert art["status"] == "GRANTED-mock"


def test_sandbox_handshake_constructs_correct_calls(monkeypatch):
    monkeypatch.setattr(abdm, "CLIENT_ID", "test-id")
    monkeypatch.setattr(abdm, "CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("ABDM_MODE", "sandbox")
    monkeypatch.setattr("backend.config.ABDM_MODE", "sandbox")
    monkeypatch.setattr(abdm, "ABDM_MODE", "sandbox")
    assert abdm.mode() == "sandbox-live"

    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw))
        if url.endswith("/sessions"):
            return _Resp({"accessToken": "tok123", "expiresIn": 3600})
        return _Resp({"status": "OK", "consentRequest": {"id": "cr-1"}})

    monkeypatch.setattr(abdm.requests, "post", fake_post)
    sess = abdm.create_session()
    assert sess == {"ok": True, "access_token": "tok123", "expires_in": 3600}
    out = abdm.request_consent("tok123", "patient@abdm", "hiu-1", "hip-1", "OPD", ["Prescription"])
    assert out["mode"] == "sandbox-live" and out["gateway_response"]["status"] == "OK"
    assert calls[0][0].endswith("/sessions")
    assert calls[1][0].endswith("/v1/consent/requests")
    assert calls[1][1]["headers"]["Authorization"] == "Bearer tok123"
    assert calls[1][1]["headers"]["X-HIP-ID"] == "hip-1"
