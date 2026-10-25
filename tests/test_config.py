import json
from pathlib import Path

from lt200b.config import ConfigStore


def test_missing_config_file_returns_empty(tmp_path: Path) -> None:
    store = ConfigStore(config_dir=tmp_path / "does_not_exist")
    assert store.load() == {}


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = ConfigStore(config_dir=tmp_path)
    store.save({"last_printer": "AA:BB:CC:DD:EE:FF"})
    assert store.load() == {"last_printer": "AA:BB:CC:DD:EE:FF"}
    assert store.path.exists()
    assert json.loads(store.path.read_text()) == {"last_printer": "AA:BB:CC:DD:EE:FF"}


def test_save_merges_with_existing_values(tmp_path: Path) -> None:
    store = ConfigStore(config_dir=tmp_path)
    store.save({"a": "1"})
    store.save({"b": "2"})
    assert store.load() == {"a": "1", "b": "2"}


def test_corrupt_config_file_returns_empty(tmp_path: Path) -> None:
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "config.json").write_text("{not json")
    assert ConfigStore(config_dir=config_dir).load() == {}
