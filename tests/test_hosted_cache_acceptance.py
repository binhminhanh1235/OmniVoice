import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "hosted_cache_acceptance.py"
spec = importlib.util.spec_from_file_location("hosted_cache_acceptance", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def evidence(*, ref="a" * 40, resource=True, wheel=True, seconds=10.0):
    return {
        "package_ref": ref,
        "resource_fast_path": resource,
        "wheel_fast_path": wheel,
        "bootstrap_seconds": seconds,
    }


def test_accepts_exact_warm_cache_that_is_faster():
    assert acceptance.evaluate(
        evidence(resource=False, wheel=False, seconds=100.0),
        evidence(resource=True, wheel=True, seconds=20.0),
    ) == []


def test_rejects_wrong_revision_or_non_fast_warm_sample():
    failures = acceptance.evaluate(
        evidence(ref="a" * 40, seconds=50.0),
        evidence(ref="b" * 40, resource=False, wheel=False, seconds=60.0),
    )

    assert any("package_ref differs" in item for item in failures)
    assert any("resource_fast_path" in item for item in failures)
    assert any("wheel_fast_path" in item for item in failures)
    assert any("not faster" in item for item in failures)
