"""Contract tests for the OpenAI-compatible singing gateway."""

from __future__ import annotations

import json
import urllib.parse

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from sing_gateway.config import SingResult
from sing_gateway.server import sing


def _client() -> TestClient:
    # https base URL so Secure cookies are sent by the test client
    return TestClient(sing.app, base_url="https://testserver")


def test_audio_block_names_the_picked_version() -> None:
    block = SingResult("https://cdn/a.mp3", "a.mp3", title="稻香", artist="周杰伦").as_block()
    assert block["type"] == "audio"
    assert block["title"] == "稻香"
    assert block["artist"] == "周杰伦"


def test_audio_block_omits_unknown_song() -> None:
    block = SingResult("https://cdn/a.mp3", "a.mp3").as_block()
    assert "title" not in block
    assert "artist" not in block


def test_health() -> None:
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lists_sing_song_model(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    response = _client().get("/v1/models", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["data"]]
    assert ids == ["sing-song", "sing-voices", "sing-search"]


def test_voices_endpoint_points_to_plaza(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    path = tmp_path / "voices.json"
    path.write_text(json.dumps({"keine": "https://example.com/keine.zip"}), encoding="utf-8")
    monkeypatch.setenv("SING_VOICES_FILE", str(path))
    response = _client().get("/v1/voices", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["plaza_url"] == "https://voice-models.flowbee.top"
    assert "音色广场" in body["note"]


def test_config_resolves_whitelist_voice(monkeypatch: MonkeyPatch, tmp_path) -> None:
    path = tmp_path / "voices.json"
    path.write_text(
        json.dumps({"cirno": {"label": "Cirno", "url": "https://example.com/cirno.zip"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SING_VOICES_FILE", str(path))
    config = sing._config({"voice": "cirno"})
    assert config.voice_model_url == "https://example.com/cirno.zip"


def test_requires_gateway_token(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    response = _client().post(
        "/v1/chat/completions",
        json={"model": "sing-song", "messages": [{"role": "user", "content": "雨爱"}]},
    )
    assert response.status_code == 401


def test_generates_audio_block(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    captured: dict[str, object] = {}

    def fake_render(payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        return {
            "type": "audio",
            "source": {"type": "url", "url": "https://example.com/a.mp3"},
            "media_type": "audio/mpeg",
            "filename": "a.mp3",
        }

    monkeypatch.setattr(sing, "_render", fake_render)
    response = _client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={
            "model": "sing-song",
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps({"song": "雨爱", "duration": 25}, ensure_ascii=False),
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "sing-song"
    content = json.loads(body["choices"][0]["message"]["content"])
    assert content["type"] == "audio"
    assert content["source"]["url"] == "https://example.com/a.mp3"
    assert captured["song"] == "雨爱"
    assert captured["duration"] == 25


def test_plain_song_content(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    captured: dict[str, object] = {}

    def fake_render(payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        return {
            "type": "audio",
            "source": {"type": "url", "url": "https://example.com/a.mp3"},
            "media_type": "audio/mpeg",
            "filename": "a.mp3",
        }

    monkeypatch.setattr(sing, "_render", fake_render)
    response = _client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={"model": "sing-song", "messages": [{"role": "user", "content": "雨爱"}]},
    )
    assert response.status_code == 200
    assert captured["song"] == "雨爱"


def test_voices_model_returns_plaza_guide_without_rendering(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    path = tmp_path / "voices.json"
    path.write_text(json.dumps({"keine": "https://example.com/keine.zip"}), encoding="utf-8")
    monkeypatch.setenv("SING_VOICES_FILE", str(path))

    def fail_render(payload: dict[str, object]) -> dict[str, object]:
        raise AssertionError("voices model must not render")

    monkeypatch.setattr(sing, "_render", fail_render)
    response = _client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={"model": "sing-voices", "messages": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "sing-voices"
    assert body["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    content = json.loads(body["choices"][0]["message"]["content"])
    assert content["type"] == "guide"
    assert content["plaza_url"] == "https://voice-models.flowbee.top"
    assert "音色广场" in content["text"]


def test_unknown_voice_does_not_enumerate(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    path = tmp_path / "voices.json"
    path.write_text(json.dumps({"cirno": "https://example.com/cirno.zip"}), encoding="utf-8")
    monkeypatch.setenv("SING_VOICES_FILE", str(path))
    response = _client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={
            "model": "sing-song",
            "messages": [
                {"role": "user", "content": json.dumps({"song": "雨爱", "voice": "miku"})}
            ],
        },
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "unknown voice 'miku'" in detail
    assert "cirno" not in detail  # never enumerate the whitelist
    assert "voice-models.flowbee.top" in detail


def test_config_resolves_catalog_voice(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SING_VOICES_FILE", str(tmp_path / "voices.json"))
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "hatsune-miku": {
                    "label": "Hatsune Miku",
                    "url": "https://huggingface.co/a/b/resolve/main/miku.zip",
                    "favorites": 59,
                    "weights_id": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SING_VOICES_CATALOG_FILE", str(catalog))
    config = sing._config({"voice": "hatsune-miku"})
    assert config.voice_model_url == "https://huggingface.co/a/b/resolve/main/miku.zip"


def test_music_source_env_and_payload(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_MUSIC_SOURCE", "netease")
    assert sing._config({}).music_source == "netease"
    assert sing._config({"source": "bilibili"}).music_source == "bilibili"
    monkeypatch.delenv("SING_MUSIC_SOURCE")
    assert sing._config({}).music_source == "bilibili"


def test_mixing_volume_env_payload_and_clamp(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_INSTRUMENTAL_VOLUME", "0")
    monkeypatch.setenv("SING_BACKUP_VOCALS_VOLUME", "-3")
    assert sing._config({}).instrumental_volume == 0
    assert sing._config({}).backup_vocals_volume == -3
    assert sing._config({"instrumental_volume": -6}).instrumental_volume == -6
    monkeypatch.delenv("SING_INSTRUMENTAL_VOLUME")
    monkeypatch.delenv("SING_BACKUP_VOCALS_VOLUME")
    assert sing._config({}).instrumental_volume == -60
    assert sing._config({}).backup_vocals_volume == -60
    # Out-of-range values clamp instead of failing: positive gains would boost
    # and deepen negatives just mute further.
    assert sing._config({"instrumental_volume": "5"}).instrumental_volume == 0
    assert sing._config({"instrumental_volume": "-99"}).instrumental_volume == -60


def test_job_request_forwards_mixing_volumes() -> None:
    body = sing.JobRequest(song="晴天", instrumental_volume=0, backup_vocals_volume=-6)
    payload = sing._job_payload(body)
    assert payload["instrumental_volume"] == 0
    assert payload["backup_vocals_volume"] == -6
    omitted = sing._job_payload(sing.JobRequest(song="晴天"))
    assert "instrumental_volume" not in omitted
    assert "backup_vocals_volume" not in omitted


def test_client_song_error_maps_to_400(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")

    def fail_render(payload: dict[str, object]) -> dict[str, object]:
        raise sing.ClientSongError("网易云没有返回音频直链：该歌曲可能需要 VIP")

    monkeypatch.setattr(sing, "_render", fail_render)
    response = _client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={"model": "sing-song", "messages": [{"role": "user", "content": "晴天"}]},
    )
    assert response.status_code == 400
    assert "VIP" in response.json()["detail"]


def _submission_env(monkeypatch: MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("SING_VOICES_FILE", str(tmp_path / "voices.json"))
    monkeypatch.setenv("SING_VOICE_REQUESTS_FILE", str(tmp_path / "requests.json"))
    monkeypatch.setenv("SING_DB_PATH", str(tmp_path / "sing.db"))
    monkeypatch.setenv("SING_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SING_PUBLIC_BASE_URL", "https://plaza.example")
    monkeypatch.setenv("SING_UPLOAD_DAILY_LIMIT", "100")
    monkeypatch.setenv("SING_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("SING_SSO_SECRET", "test-sso-secret")
    monkeypatch.setenv("SING_JWT_TTL_HOURS", "24")
    monkeypatch.setenv("SING_PLAZA_BASE", "https://plaza.example")
    monkeypatch.setenv("SING_SSO_CLIENT_ID", "sing")
    monkeypatch.delenv("SING_SSO_URL", raising=False)
    monkeypatch.delenv("SING_REVIEW_BASE_URL", raising=False)
    monkeypatch.delenv("SING_REVIEW_API_KEY", raising=False)
    sing._recent_submissions.clear()


def _session(username: str = "alice", uid: int = 7) -> dict[str, str]:
    from sing_gateway.server import sso

    token = sso.issue_session(sso.Identity(uid=uid, username=username, name=username.title()))
    return {"sing_session": token}


def _model_zip_bytes() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("model.pth", b"stub-weights")
    return buffer.getvalue()


def test_submit_upload_auto_approves_and_registers_voice(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    _submission_env(monkeypatch, tmp_path)
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "My Voice"},
        files={"file": ("model.zip", _model_zip_bytes(), "application/zip")},
        cookies=_session(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["name"].startswith("my-voice-")
    voices = json.loads((tmp_path / "voices.json").read_text(encoding="utf-8"))
    entry = voices[body["name"]]
    assert entry["label"] == "My Voice"
    assert entry["added_by"] == "alice"
    assert entry["url"] == f"https://plaza.example/uploads/{body['name']}.zip"
    assert (tmp_path / "uploads" / f"{body['name']}.zip").exists()

    status = _client().get(body["status_path"])
    assert status.status_code == 200
    assert status.json()["flowbee_user"] == "alice"
    assert status.json()["flowbee_uid"] == 7


def test_submit_link_uses_source_url(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)

    def fake_download(url: str, dest, max_bytes: int) -> None:
        dest.write_bytes(_model_zip_bytes())

    monkeypatch.setattr(sing, "_download_zip", fake_download)
    response = _client().post(
        "/v1/voice-requests",
        json={"label": "Linked Voice", "url": "https://huggingface.co/a/b/resolve/main/m.zip"},
        cookies=_session("bob", 8),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    voices = json.loads((tmp_path / "voices.json").read_text(encoding="utf-8"))
    assert voices[body["name"]]["url"] == "https://huggingface.co/a/b/resolve/main/m.zip"
    assert voices[body["name"]]["added_by"] == "bob"


def test_submit_rejects_unsafe_pickle(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    import io
    import zipfile

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as payload:
        payload.writestr("archive/data.pkl", b"cposix\nsystem\n.")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("model.pth", inner.getvalue())
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "Evil"},
        files={"file": ("model.zip", buffer.getvalue(), "application/zip")},
        cookies=_session("eve", 9),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert "posix.system" in body["reason"]
    assert not (tmp_path / "voices.json").exists()


def test_submit_requires_login(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "No Login"},
        files={"file": ("model.zip", _model_zip_bytes(), "application/zip")},
    )
    assert response.status_code == 401


def test_submit_rejects_non_public_link(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    response = _client().post(
        "/v1/voice-requests",
        json={"label": "SSRF", "url": "http://127.0.0.1:9001/health"},
        cookies=_session("carol", 10),
    )
    assert response.status_code == 400
    assert "公网" in response.json()["detail"]


def test_status_endpoint_404(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    response = _client().get("/v1/voice-requests/vr-missing")
    assert response.status_code == 404


def test_submit_upload_uses_huggingface_storage(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    monkeypatch.delenv("SING_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("SING_PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("SING_HF_REPO", "leicanxi/rvc-models")
    monkeypatch.setenv("SING_HF_TOKEN", "hf_test")
    captured: dict[str, str] = {}

    def fake_upload(local_path, *, repo_id: str, path_in_repo: str, token: str) -> str:
        captured.update(
            {
                "repo_id": repo_id,
                "path_in_repo": path_in_repo,
                "token": token,
                "exists": str(local_path),
            }
        )
        return f"https://huggingface.co/{repo_id}/resolve/main/{path_in_repo}"

    monkeypatch.setattr(sing, "hf_upload", fake_upload)
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "HF Voice"},
        files={"file": ("model.zip", _model_zip_bytes(), "application/zip")},
        cookies=_session("dave", 11),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["name"].startswith("hf-voice-")
    assert captured["repo_id"] == "leicanxi/rvc-models"
    assert captured["path_in_repo"] == f"uploads/{body['name']}.zip"
    assert captured["token"] == "hf_test"
    voices = json.loads((tmp_path / "voices.json").read_text(encoding="utf-8"))
    assert voices[body["name"]]["source"] == "hf"
    assert voices[body["name"]]["url"].startswith("https://huggingface.co/")


def test_submit_file_requires_storage(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    monkeypatch.delenv("SING_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("SING_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("SING_HF_REPO", raising=False)
    monkeypatch.delenv("SING_HF_TOKEN", raising=False)
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "No Storage"},
        files={"file": ("model.zip", _model_zip_bytes(), "application/zip")},
        cookies=_session("erin", 12),
    )
    assert response.status_code == 503
    assert "存储" in response.json()["detail"]


def test_submit_upload_uses_modelscope_storage(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    monkeypatch.delenv("SING_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("SING_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("SING_HF_REPO", raising=False)
    monkeypatch.delenv("SING_HF_TOKEN", raising=False)
    monkeypatch.setenv("SING_MS_REPO", "leicanxi/rvc-voice-uploads")
    monkeypatch.setenv("SING_MS_TOKEN", "ms_test")
    captured: dict[str, str] = {}

    def fake_upload(local_path, *, repo_id: str, path_in_repo: str, token: str) -> str:
        captured.update({"repo_id": repo_id, "path_in_repo": path_in_repo, "token": token})
        return f"https://modelscope.cn/models/{repo_id}/resolve/master/{path_in_repo}"

    monkeypatch.setattr(sing, "modelscope_upload", fake_upload)
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "MS Voice"},
        files={"file": ("model.zip", _model_zip_bytes(), "application/zip")},
        cookies=_session("frank", 13),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert captured["repo_id"] == "leicanxi/rvc-voice-uploads"
    assert captured["path_in_repo"] == f"uploads/{body['name']}.zip"
    voices = json.loads((tmp_path / "voices.json").read_text(encoding="utf-8"))
    assert voices[body["name"]]["source"] == "ms"
    assert voices[body["name"]]["url"].startswith("https://modelscope.cn/")


def test_auth_login_redirects_to_sso(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    response = _client().get("/v1/auth/login?next=/upload.html", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://flowbee.top/sso/sing?")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["state"][0]
    cookie = response.cookies.get("sing_sso")
    assert cookie == f"{state}.upload"


def test_auth_callback_issues_session(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    import time

    import jwt as pyjwt

    client = _client()
    login = client.get("/v1/auth/login?next=/upload.html", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    code = pyjwt.encode(
        {
            "sub": "7",
            "username": "alice",
            "name": "Alice",
            "exp": int(time.time()) + 300,
        },
        "test-sso-secret",
        algorithm="HS256",
    )
    callback = client.get(f"/v1/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert callback.status_code == 302
    assert callback.headers["location"] == "https://plaza.example/upload.html"

    me = client.get("/v1/auth/me")
    assert me.status_code == 200
    assert me.json() == {"uid": 7, "username": "alice", "name": "Alice"}


def test_auth_callback_rejects_state_mismatch(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    import time

    import jwt as pyjwt

    client = _client()
    client.get("/v1/auth/login?next=/upload.html", follow_redirects=False)
    code = pyjwt.encode(
        {"sub": "7", "username": "alice", "exp": int(time.time()) + 300},
        "test-sso-secret",
        algorithm="HS256",
    )
    callback = client.get(
        f"/v1/auth/callback?code={code}&state=wrong-state", follow_redirects=False
    )
    assert callback.status_code == 302
    assert "login=failed" in callback.headers["location"]


def test_auth_callback_rejects_expired_code(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    import time

    import jwt as pyjwt

    client = _client()
    login = client.get("/v1/auth/login?next=/upload.html", follow_redirects=False)
    state = login.headers["location"].split("state=", 1)[1]
    code = pyjwt.encode(
        {"sub": "7", "username": "alice", "exp": int(time.time()) - 3600},
        "test-sso-secret",
        algorithm="HS256",
    )
    callback = client.get(f"/v1/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert callback.status_code == 302
    assert "login=failed" in callback.headers["location"]


def test_me_requires_login(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    assert _client().get("/v1/auth/me").status_code == 401


def test_my_requests_filters_by_uid(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    subs.save_request(
        subs.build_request_record(
            request_id="vr-a",
            name="a-aaaa",
            label="A",
            url="u",
            flowbee_user="alice",
            source="upload",
            approved=True,
            reason="ok",
            flowbee_uid=7,
        )
    )
    subs.save_request(
        subs.build_request_record(
            request_id="vr-b",
            name="b-bbbb",
            label="B",
            url="u",
            flowbee_user="bob",
            source="upload",
            approved=True,
            reason="ok",
            flowbee_uid=8,
        )
    )
    response = _client().get("/v1/voice-requests/mine", cookies=_session())
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["submissions"]] == ["vr-a"]


def test_delete_requires_owner(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    subs.save_request(
        subs.build_request_record(
            request_id="vr-b",
            name="b-bbbb",
            label="B",
            url="u",
            flowbee_user="bob",
            source="upload",
            approved=True,
            reason="ok",
            flowbee_uid=8,
        )
    )
    response = _client().delete("/v1/voice-requests/vr-b", cookies=_session())
    assert response.status_code == 404


def test_delete_removes_whitelist_and_file(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    name = "mine-1a2b"
    (tmp_path / "voices.json").write_text(
        json.dumps({name: {"label": "Mine", "url": "u"}}), encoding="utf-8"
    )
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / f"{name}.zip").write_bytes(b"zip")
    subs.save_request(
        subs.build_request_record(
            request_id="vr-a",
            name=name,
            label="Mine",
            url="u",
            flowbee_user="alice",
            source="upload",
            approved=True,
            reason="ok",
            flowbee_uid=7,
        )
    )
    response = _client().delete("/v1/voice-requests/vr-a", cookies=_session())
    assert response.status_code == 200
    assert response.json()["name"] == name
    assert name not in json.loads((tmp_path / "voices.json").read_text(encoding="utf-8"))
    assert not (uploads / f"{name}.zip").exists()
    record = subs.get_request("vr-a")
    assert record is not None and record["status"] == "deleted"


def test_origin_check_blocks_foreign_host(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    response = _client().post(
        "/v1/voice-requests",
        data={"label": "X"},
        headers={"origin": "https://evil.example"},
        cookies=_session(),
    )
    assert response.status_code == 403


def test_search_endpoint_returns_candidates(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    calls: dict[str, object] = {}

    def fake_search(query: str, limit: int = 3, source: str = "bilibili"):
        from sing_gateway.config import SongCandidate

        calls.update({"query": query, "limit": limit, "source": source})
        return [
            SongCandidate(
                title="起风了", artist="买辣椒也用券", duration_seconds=327, url="https://b/BV1"
            )
        ]

    monkeypatch.setattr(sing, "search_songs", fake_search)
    response = _client().post(
        "/v1/songs/search",
        headers={"Authorization": "Bearer secret"},
        json={"query": "  起风了 ", "limit": 3, "source": "netease"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "起风了"
    assert body["data"][0]["title"] == "起风了"
    assert body["data"][0]["url"] == "https://b/BV1"
    assert calls == {"query": "起风了", "limit": 3, "source": "netease"}


def test_search_endpoint_requires_token(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    response = _client().post("/v1/songs/search", json={"query": "x"})
    assert response.status_code == 401


def test_search_endpoint_rejects_empty_query(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    response = _client().post(
        "/v1/songs/search",
        headers={"Authorization": "Bearer secret"},
        json={"query": "   "},
    )
    assert response.status_code == 400


def test_search_model_returns_candidates_without_rendering(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")

    def fail_render(payload: dict[str, object]) -> dict[str, object]:
        raise AssertionError("search model must not render")

    monkeypatch.setattr(sing, "_render", fail_render)
    seen: dict[str, object] = {}

    def fake_search(query: str, limit: int = 3, source: str = "bilibili"):
        from sing_gateway.config import SongCandidate

        seen.update({"query": query, "limit": limit, "source": source})
        return [
            SongCandidate(title="晴天", artist="周杰伦", duration_seconds=269, url="https://b/BV9")
        ]

    monkeypatch.setattr(sing, "search_songs", fake_search)
    response = _client().post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer secret"},
        json={
            "model": "sing-search",
            "messages": [{"role": "user", "content": json.dumps({"query": "晴天", "limit": 3})}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "sing-search"
    content = json.loads(body["choices"][0]["message"]["content"])
    assert content["type"] == "candidates"
    assert content["data"][0]["title"] == "晴天"
    assert seen == {"query": "晴天", "limit": 3, "source": "bilibili"}


def test_models_endpoint_lists_search_model(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    response = _client().get("/v1/models", headers={"Authorization": "Bearer secret"})
    ids = [item["id"] for item in response.json()["data"]]
    assert ids == ["sing-song", "sing-voices", "sing-search"]


def test_auth_callback_rejects_wrong_audience(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    import time

    import jwt as pyjwt

    client = _client()
    login = client.get("/v1/auth/login?next=/upload.html", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(login.headers["location"]).query)["state"][
        0
    ]
    code = pyjwt.encode(
        {
            "sub": "7",
            "username": "alice",
            "aud": "beewith",
            "exp": int(time.time()) + 300,
        },
        "test-sso-secret",
        algorithm="HS256",
    )
    callback = client.get(f"/v1/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert callback.status_code == 302
    assert "login=failed" in callback.headers["location"]


def test_auth_callback_accepts_legacy_ticket_without_audience(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    _submission_env(monkeypatch, tmp_path)
    import time

    import jwt as pyjwt

    client = _client()
    login = client.get("/v1/auth/login?next=/upload.html", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(login.headers["location"]).query)["state"][
        0
    ]
    code = pyjwt.encode(
        {"sub": "7", "username": "alice", "exp": int(time.time()) + 300},
        "test-sso-secret",
        algorithm="HS256",
    )
    callback = client.get(f"/v1/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert callback.status_code == 302
    assert callback.headers["location"] == "https://plaza.example/upload.html"


def _approved_record(uid: int = 7, name: str = "mine-1a2b") -> dict[str, object]:
    from sing_gateway import submissions as subs

    return subs.build_request_record(
        request_id=f"vr-{name}",
        name=name,
        label="Mine",
        url="https://example.com/m.zip",
        flowbee_user="alice" if uid == 7 else "bob",
        source="upload",
        approved=True,
        reason="ok",
        flowbee_uid=uid,
        tags=["女声", "测试"],
        language="zh",
        gender="female",
    )


def test_publish_makes_voice_public_and_unpublish_removes(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    subs.save_request(_approved_record())

    response = _client().post("/v1/voice-requests/vr-mine-1a2b/publish", cookies=_session())
    assert response.status_code == 200
    assert response.json()["submission"]["visibility"] == "public"

    listing = _client().get("/v1/voices/public").json()["voices"]
    assert [item["name"] for item in listing] == ["mine-1a2b"]
    assert listing[0]["tags"] == ["女声", "测试"]
    assert listing[0]["author"] == "社区投稿"
    assert "flowbee_uid" not in listing[0]
    assert "flowbee_user" not in listing[0]

    unpublish = _client().post("/v1/voice-requests/vr-mine-1a2b/unpublish", cookies=_session())
    assert unpublish.status_code == 200
    assert _client().get("/v1/voices/public").json()["voices"] == []


def test_publish_requires_owner(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    subs.save_request(_approved_record())
    response = _client().post(
        "/v1/voice-requests/vr-mine-1a2b/publish", cookies=_session("bob", 8)
    )
    assert response.status_code == 404


def test_publish_requires_approved(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    record = subs.build_request_record(
        request_id="vr-bad",
        name="",
        label="Bad",
        url="",
        flowbee_user="alice",
        source="upload",
        approved=False,
        reason="nope",
        flowbee_uid=7,
    )
    subs.save_request(record)
    response = _client().post("/v1/voice-requests/vr-bad/publish", cookies=_session())
    assert response.status_code == 400
    assert "审核通过" in response.json()["detail"]


def test_public_list_sorts_by_usage(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    subs.save_request(_approved_record(name="a-aaaa"))
    subs.save_request(_approved_record(name="b-bbbb"))
    _client().post("/v1/voice-requests/vr-a-aaaa/publish", cookies=_session())
    _client().post("/v1/voice-requests/vr-b-bbbb/publish", cookies=_session())
    subs.increment_usage("a-aaaa")
    subs.increment_usage("b-bbbb")
    subs.increment_usage("b-bbbb")

    hot = _client().get("/v1/voices/public?sort=hot").json()["voices"]
    assert [item["name"] for item in hot] == ["b-bbbb", "a-aaaa"]
    assert hot[0]["uses"] == 2


def test_moderation_blocks_public_voice_and_prevents_republish(
    monkeypatch: MonkeyPatch, tmp_path
) -> None:
    _submission_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SING_GATEWAY_TOKEN", "secret")
    from sing_gateway import submissions as subs

    subs.save_request(_approved_record())
    _client().post("/v1/voice-requests/vr-mine-1a2b/publish", cookies=_session())

    response = _client().post(
        "/v1/voice-requests/vr-mine-1a2b/moderate",
        headers={"Authorization": "Bearer secret"},
        json={"moderation": "blocked", "reason": "copyright"},
    )
    assert response.status_code == 200
    assert response.json()["submission"]["moderation"] == "blocked"
    assert response.json()["submission"]["visibility"] == "private"
    assert _client().get("/v1/voices/public").json()["voices"] == []

    republish = _client().post(
        "/v1/voice-requests/vr-mine-1a2b/publish", cookies=_session()
    )
    assert republish.status_code == 400
    assert "下架" in republish.json()["detail"]


def test_render_increments_voice_usage(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    (tmp_path / "voices.json").write_text(
        json.dumps({"cirno": "https://example.com/cirno.zip"}), encoding="utf-8"
    )
    from sing_gateway import submissions as subs

    monkeypatch.setattr(
        sing,
        "render_song",
        lambda url, cfg: SingResult("https://cdn/a.mp3", "a.mp3"),
    )
    block = sing._render({"voice": "cirno", "url": "https://example.com/song.mp3"})
    assert block["type"] == "audio"
    assert subs.get_usage("cirno") == 1


def test_events_record_publish_unpublish_delete(monkeypatch: MonkeyPatch, tmp_path) -> None:
    _submission_env(monkeypatch, tmp_path)
    from sing_gateway import submissions as subs

    subs.save_request(_approved_record())
    subs.add_event(
        "vr-mine-1a2b", "mine-1a2b", "approved", actor_uid=7, actor_role="system"
    )
    _client().post("/v1/voice-requests/vr-mine-1a2b/publish", cookies=_session())
    _client().post("/v1/voice-requests/vr-mine-1a2b/unpublish", cookies=_session())
    _client().delete("/v1/voice-requests/vr-mine-1a2b", cookies=_session())

    actions = [item["action"] for item in subs.list_events("vr-mine-1a2b")]
    assert actions == ["approved", "published", "unpublished", "deleted"]
