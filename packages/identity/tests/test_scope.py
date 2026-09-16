import pytest

from atp_identity.scope import covers, matches, scope_covers, scope_matches, validate_pattern


@pytest.mark.parametrize(
    ("pattern", "resource", "expected"),
    [
        ("*", "vendor:128", True),
        ("vendor:*", "vendor:128", True),
        ("vendor:128", "vendor:128", True),
        ("vendor:128", "vendor:129", False),
        ("vendor:*", "invoice:1", False),
        ("vendor:*", "vendor:*", False),  # a concrete resource is never a wildcard
    ],
)
def test_matches(pattern: str, resource: str, expected: bool) -> None:
    assert matches(pattern, resource) is expected


@pytest.mark.parametrize(
    ("parent", "child", "expected"),
    [
        ("*", "vendor:*", True),
        ("*", "*", True),
        ("vendor:*", "*", False),
        ("vendor:*", "vendor:128", True),
        ("vendor:128", "vendor:*", False),
        ("vendor:128", "vendor:128", True),
        ("vendor:*", "invoice:*", False),
    ],
)
def test_covers(parent: str, child: str, expected: bool) -> None:
    assert covers(parent, child) is expected


def test_scope_helpers() -> None:
    assert scope_covers(["vendor:*", "invoice:*"], ["invoice:7"])
    assert not scope_covers(["vendor:*"], ["invoice:7"])
    assert scope_matches(["vendor:*"], "vendor:1")
    assert not scope_matches(["vendor:*"], "invoice:1")


def test_validate_pattern_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        validate_pattern("vendor")
    with pytest.raises(ValueError):
        validate_pattern(":x")
