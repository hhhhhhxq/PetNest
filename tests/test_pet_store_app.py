from __future__ import annotations

import json
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.parse import unquote, urlparse
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image
import pytest

from petnest.app import PetNest
from petnest.core.pet_package_importer import PetImportResult
from petnest.core.pet_store_catalog import PetStoreCatalog
from petnest.core.pet_store_cache import PetStoreCache
from petnest.core.pet_store_service import PetStoreInstallResult
from petnest.core.pet_store_service import PetStoreService
from petnest.core.pet_store_state import PetStoreStateStore
from petnest.core.settings_manager import SettingsManager
from petnest.ui.pet_store_page import PetStorePage
from tests.test_pet_store_catalog import _catalog, _pet
from tools.create_sample_pet import create_sample_pet


def _application(tmp_path: Path, qtbot: object) -> PetNest:
    create_sample_pet(tmp_path / "pets" / "sample_pet")
    application = PetNest(
        pets_root=tmp_path / "pets",
        settings_manager=SettingsManager(tmp_path / "settings.json"),
        store_base_url="https://store.example",
        enable_tray=False,
    )
    qtbot.addWidget(application.window)
    return application


def _store_result(root: Path, identifier: str) -> PetStoreInstallResult:
    raw = _catalog(_pet(identifier))
    raw["featured_pet_id"] = identifier
    item = PetStoreCatalog.from_dict(raw).pet(identifier)
    assert item is not None
    return PetStoreInstallResult(
        item,
        PetImportResult(identifier, root, None, False),
    )


def _create_pet(root: Path, identifier: str) -> Path:
    create_sample_pet(root)
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["id"] = identifier
    config["name"] = identifier
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return root


def test_app_constructs_store_service_with_injected_base_url(qtbot: object, tmp_path: Path) -> None:
    application = _application(tmp_path, qtbot)

    assert application.pet_store_cache.base_url == "https://store.example"
    assert application.pet_store_service.pets_root == application.pets_root.resolve()
    application.shutdown()


def test_store_install_refreshes_library_without_switching_to_new_pet(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    store_root = _create_pet(tmp_path / "pets" / "store_pet", "store_pet")
    result = _store_result(store_root, "store_pet")
    completions: list[str] = []
    refreshes: list[str] = []
    application._pet_action_exchange_dialog = SimpleNamespace(
        complete_store_install=completions.append,
        complete_store_install_failure=lambda message: pytest.fail(message),
        refresh_packages=lambda _packages, current_id: refreshes.append(current_id) or True,
    )  # type: ignore[assignment]
    monkeypatch.setattr(
        application,
        "switch_pet",
        lambda _identifier: pytest.fail("商店安装不应切换当前宠物"),
    )

    application._handle_store_pet_installed("store_pet", result)

    assert application.package.identifier == "sample_pet"
    assert any(package.identifier == "store_pet" for package in application.packages)
    assert completions and "领养" in completions[0]
    assert refreshes == ["sample_pet"]
    application._pet_action_exchange_dialog = None
    application.shutdown()


def test_store_update_of_current_pet_reloads_in_place(
    qtbot: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application = _application(tmp_path, qtbot)
    result = _store_result(application.package.root, application.package.identifier)
    reloads: list[bool] = []
    completions: list[str] = []
    application._pet_action_exchange_dialog = SimpleNamespace(
        complete_store_install=completions.append,
        complete_store_install_failure=lambda message: pytest.fail(message),
        refresh_packages=lambda *_args: True,
    )  # type: ignore[assignment]
    monkeypatch.setattr(
        application,
        "reload_current_pet",
        lambda *, synchronize=False: reloads.append(synchronize) or True,
    )

    application._handle_store_pet_installed(application.package.identifier, result)

    assert reloads == [False]
    assert completions
    application._pet_action_exchange_dialog = None
    application.shutdown()


def _png_bytes(width: int, height: int) -> bytes:
    stream = BytesIO()
    Image.new("RGBA", (width, height), (20, 30, 40, 255)).save(stream, format="PNG")
    return stream.getvalue()


def _sha_file(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.as_posix().split("/served/", 1)[-1],
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_served_store(root: Path, *, description: str, updated_at: str) -> None:
    product = root / "served" / "store" / "pets" / "store_pet"
    product.mkdir(parents=True, exist_ok=True)
    (product / "cover.png").write_bytes(_png_bytes(32, 32))
    (product / "idle-preview.png").write_bytes(_png_bytes(32 * 4, 32))
    source = root / f"source-{hashlib.sha256(description.encode()).hexdigest()[:8]}"
    _create_pet(source, "store_pet")
    config_path = source / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["description"] = description
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with ZipFile(product / "package.zip", "w", ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())
    catalog = {
        "schema_version": 1,
        "generated_at": updated_at,
        "featured_pet_id": "store_pet",
        "pets": [
            {
                "id": "store_pet",
                "name": "Store Pet",
                "author": "PetNest",
                "summary": description,
                "tags": ["官方"],
                "updated_at": updated_at,
                "action_count": 9,
                "capabilities": ["click"],
                "cover": _sha_file(product / "cover.png"),
                "idle_preview": {
                    **_sha_file(product / "idle-preview.png"),
                    "frame_width": 32,
                    "frame_height": 32,
                    "frame_count": 4,
                    "frame_durations_ms": [125, 125, 125, 125],
                },
                "package": _sha_file(product / "package.zip"),
            }
        ],
    }
    catalog_path = root / "served" / "store" / "catalog.json"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")


class _StoreHandler(BaseHTTPRequestHandler):
    root: Path

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/v1/store/catalog.json":
            relative = "store/catalog.json"
        elif parsed.path.startswith("/v1/store/files/"):
            relative = unquote(parsed.path[len("/v1/store/files/") :])
        else:
            self.send_error(404)
            return
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root.resolve()) or not target.is_file():
            self.send_error(404)
            return
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_store_end_to_end_adopt_then_detect_update(qtbot: object, tmp_path: Path) -> None:
    _write_served_store(
        tmp_path,
        description="first release",
        updated_at="2026-08-18T08:00:00Z",
    )
    handler = type("StoreHandler", (_StoreHandler,), {"root": tmp_path / "served"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        cache = PetStoreCache(tmp_path / "cache", base_url)
        state = PetStoreStateStore(tmp_path / "cache" / "state.json")
        service = PetStoreService(cache, state, tmp_path / "pets")
        page = PetStorePage(service)
        qtbot.addWidget(page)
        page.show()
        page.pet_install_ready.connect(
            lambda _pet_id, _result: page.complete_install("领养完成")
        )

        page.activate()
        qtbot.waitUntil(lambda: page.visible_pet_ids() == ["store_pet"], timeout=5000)
        page.show_detail("store_pet")
        page.trigger_primary()
        qtbot.waitUntil(
            lambda: page.footer_state().primary_text == "已领养", timeout=5000
        )

        _write_served_store(
            tmp_path,
            description="second release",
            updated_at="2026-08-18T09:00:00Z",
        )
        page.refresh_catalog()
        qtbot.waitUntil(
            lambda: page.footer_state().primary_text == "更新", timeout=5000
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)
