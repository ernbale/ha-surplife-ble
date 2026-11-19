from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "surplife_ble"


def test_manifest_is_local_polling_with_bluetooth_discovery() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "surplife_ble"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "local_polling"
    assert "bluetooth" in manifest
    assert isinstance(manifest["bluetooth"], list)
    assert len(manifest["bluetooth"]) >= 1
    assert "version" in manifest
    assert "codeowners" in manifest
    assert "issue_tracker" in manifest
    assert "bleak-retry-connector" in " ".join(manifest["requirements"])


def test_home_assistant_modules_parse_without_importing_home_assistant() -> None:
    for path in INTEGRATION.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_translations_match_strings() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    assert english == strings


def test_manifest_declares_the_curtain_requirements() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.1"
    assert not any("lz4" in requirement.lower() for requirement in manifest["requirements"])
    # Home Assistant core already bundles Pillow, so it must not be pinned here.
    assert not any("pillow" in requirement.lower() for requirement in manifest["requirements"])
    assert "media_source" in manifest["dependencies"]


def test_services_are_described_in_yaml_and_translations() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    yaml_text = (INTEGRATION / "services.yaml").read_text(encoding="utf-8")
    fields = {
        "upload_animation": {
            "path", "url", "speed", "brightness", "mode",
            "controller_side", "flip", "max_frames", "resample",
        },
        "play_animation": {"mode", "speed", "brightness"},
    }  # fmt: skip
    for service, names in fields.items():
        assert f"\n{service}:" in f"\n{yaml_text}"
        assert set(strings["services"][service]["fields"]) == names
        for name in names:
            assert f"    {name}:" in yaml_text
        assert "flash" in strings["services"][service]["description"].lower() or (
            service == "play_animation"
        )


def test_platforms_cover_the_curtain_entities() -> None:
    const = (INTEGRATION / "const.py").read_text(encoding="utf-8")
    for platform in ("light", "media_player", "image", "number"):
        assert f'"{platform}"' in const
        assert (INTEGRATION / f"{platform}.py").exists()
