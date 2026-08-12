"""Firebase 远程伙伴配置、凭据与消息边界测试。"""

from __future__ import annotations

import json
import os
from time import time

import pytest

from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.core.remote_interaction_service import (
    FirebaseConfig,
    FirebaseRemoteInteractionService,
    RemoteCredentialStore,
    _apply_stream_change,
    _decode_remote_message,
    normalize_pair_code,
)
from petnest.models.lan_interaction import InteractionDraft, InteractionKind, LanPeer


def test_firebase_config_loads_from_file_and_requires_https(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PETNEST_FIREBASE_API_KEY", raising=False)
    monkeypatch.delenv("PETNEST_FIREBASE_DATABASE_URL", raising=False)
    (tmp_path / "firebase.json").write_text(
        json.dumps({"api_key": "public-key", "database_url": "https://petnest.example/"}),
        encoding="utf-8",
    )

    assert FirebaseConfig.load(tmp_path) == FirebaseConfig("public-key", "https://petnest.example")

    (tmp_path / "firebase.json").write_text(
        json.dumps({"api_key": "public-key", "database_url": "http://petnest.example"}),
        encoding="utf-8",
    )
    assert FirebaseConfig.load(tmp_path) is None


def test_firebase_config_loads_original_google_services_json(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PETNEST_FIREBASE_API_KEY", raising=False)
    monkeypatch.delenv("PETNEST_FIREBASE_DATABASE_URL", raising=False)
    (tmp_path / "google-services.json").write_text(
        json.dumps(
            {
                "project_info": {
                    "project_number": "123456789",
                    "project_id": "petnest-demo",
                    "firebase_url": "https://petnest-demo-default-rtdb.asia-southeast1.firebasedatabase.app",
                },
                "client": [
                    {
                        "client_info": {
                            "mobilesdk_app_id": "1:123456789:android:abcdef",
                            "android_client_info": {"package_name": "com.example.petnest"},
                        },
                        "api_key": [{"current_key": "android-project-api-key"}],
                    }
                ],
                "configuration_version": "1",
            }
        ),
        encoding="utf-8",
    )

    assert FirebaseConfig.load(tmp_path) == FirebaseConfig(
        "android-project-api-key",
        "https://petnest-demo-default-rtdb.asia-southeast1.firebasedatabase.app",
        "petnest-demo",
    )


def test_google_services_without_realtime_database_url_is_not_accepted(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PETNEST_FIREBASE_API_KEY", raising=False)
    monkeypatch.delenv("PETNEST_FIREBASE_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "petnest.core.remote_interaction_service._google_services_paths",
        lambda directory: (directory / "google-services.json",),
    )
    (tmp_path / "google-services.json").write_text(
        json.dumps(
            {
                "project_info": {"project_id": "petnest-demo"},
                "client": [{"api_key": [{"current_key": "android-project-api-key"}]}],
            }
        ),
        encoding="utf-8",
    )

    assert FirebaseConfig.load(tmp_path) is None


def test_remote_credentials_are_separate_and_owner_restricted(tmp_path) -> None:
    path = tmp_path / "firebase-remote-credentials.json"
    store = RemoteCredentialStore(path)
    store.save({"uid": "uid-1", "refresh_token": "secret", "pair_code": "23456789AB"})

    assert store.load() == {"uid": "uid-1", "refresh_token": "secret", "pair_code": "23456789AB"}
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_pair_codes_are_normalized_and_unconfigured_service_stays_off(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert normalize_pair_code("2345-6789-ab") == "23456789AB"
    assert normalize_pair_code("short") is None
    monkeypatch.setattr(
        "petnest.core.remote_interaction_service._google_services_paths",
        lambda directory: (directory / "google-services.json",),
    )

    service = FirebaseRemoteInteractionService(
        display_name="小平安",
        pet_name="平安",
        config_directory=tmp_path,
        config=None,
    )

    assert len(service.pair_code) == 10
    assert service.is_configured is False
    assert service.start() is False
    assert service.is_running is False


def test_invalid_refresh_token_rotates_pair_code_with_new_anonymous_identity(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RemoteCredentialStore(tmp_path / "firebase-remote-credentials.json")
    store.save({"uid": "old-uid", "refresh_token": "expired", "pair_code": "23456789AB"})
    service = FirebaseRemoteInteractionService(
        display_name="小平安",
        pet_name="平安",
        config_directory=tmp_path,
        config=FirebaseConfig("public-key", "https://petnest.example"),
    )

    def fake_request(url: str, **_kwargs):
        if "securetoken" in url:
            raise ValueError("expired")
        return {"idToken": "new-token", "localId": "new-uid", "refreshToken": "new-refresh"}

    monkeypatch.setattr("petnest.core.remote_interaction_service._request_json", fake_request)

    assert service._authenticate() == ("new-token", "new-uid")
    assert service.pair_code != "23456789AB"
    assert store.load()["uid"] == "new-uid"


def test_stream_changes_update_nested_account_without_mutating_source() -> None:
    original = {"partners": {"one": {"display_name": "一号"}}}
    updated = _apply_stream_change(
        original,
        {"path": "/partners/two", "data": {"display_name": "二号"}},
        patch=False,
    )
    removed = _apply_stream_change(updated, {"path": "/partners/one", "data": None}, patch=False)

    assert set(original["partners"]) == {"one"}
    assert set(updated["partners"]) == {"one", "two"}
    assert set(removed["partners"]) == {"two"}


def test_remote_message_reuses_existing_protocol_validation() -> None:
    draft = InteractionDraft.quick("receiver", InteractionKind.HEART)
    payload = LanPacketCodec.interaction(draft, "sender", "远程伙伴")
    payload["expires_at"] = int((time() + 60) * 1000)

    received = _decode_remote_message(payload, local_uid="receiver")

    assert received.sender_device_id == "sender"
    assert received.draft.kind is InteractionKind.HEART
    payload["expires_at"] = int((time() - 1) * 1000)
    with pytest.raises(LanProtocolError, match="已过期"):
        _decode_remote_message(payload, local_uid="receiver")


def test_remote_send_worker_emits_success_only_after_firebase_write(tmp_path, monkeypatch, qtbot) -> None:
    service = FirebaseRemoteInteractionService(
        display_name="小平安",
        pet_name="平安",
        config_directory=tmp_path,
        config=FirebaseConfig("public-key", "https://petnest.example"),
    )
    draft = InteractionDraft.quick("receiver", InteractionKind.GREETING)
    service._token = "token"
    service._uid = "sender"
    with service._peers_lock:
        service._peers["receiver"] = LanPeer("receiver", "对方", "平安", transport="remote")
    succeeded: list[object] = []
    failed: list[object] = []
    service.interaction_send_succeeded.connect(succeeded.append)
    service.interaction_send_failed.connect(lambda item, message: failed.append((item, message)))
    monkeypatch.setattr("petnest.core.remote_interaction_service._request_json", lambda *_args, **_kwargs: {})

    service._send_interaction_worker(draft, "token", "sender")

    assert succeeded == [draft]
    assert failed == []
