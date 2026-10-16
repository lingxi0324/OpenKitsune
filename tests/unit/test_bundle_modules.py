import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SCRIPT = PROJECT_ROOT / "build" / "bundle_modules.py"


def _load_bundle_module():
    spec = importlib.util.spec_from_file_location("bundle_modules", BUNDLE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bundle_script_loads_all_modules_from_the_shared_manifest():
    module = _load_bundle_module()

    assert set(module.MODULE_DEFS) == {"vector-memory", "whisper", "orchestration"}
    assert module.load_module_defs(module.MODULES_MANIFEST_PATH) == module.MODULE_DEFS


def test_shared_module_definitions_have_package_lists():
    module = _load_bundle_module()

    assert all(definition["packages"] for definition in module.MODULE_DEFS.values())
    assert "sentence-transformers>=2.2.0,<3.0" in module.MODULE_DEFS["vector-memory"]["packages"]
    assert "openai-whisper>=20231117" in module.MODULE_DEFS["whisper"]["packages"]
    assert "pyzmq>=25.0.0" in module.MODULE_DEFS["orchestration"]["packages"]


def test_bundle_parser_defaults_to_the_domestic_mirror():
    module = _load_bundle_module()

    args = module.build_parser().parse_args([])

    assert args.mirror == module.DEFAULT_PIP_INDEX_URL
    assert args.mirror == "https://mirrors.aliyun.com/pypi/simple/"
