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


@pytest.mark.parametrize(
    ("pattern", "resource", "expected"),
    [
        ("path:/work/*", "path:/work/a.txt", True),
        ("path:/work/*", "path:/work/sub/b.txt", True),
        ("path:/work/*", "path:/worker/x", False),
        ("path:/work*", "path:/worker/x", True),  # textual prefix: end directories with '/'
        ("path:/work/*", "path:/etc/passwd", False),
        ("path:/work/*", "path:/work/*", False),  # concrete resources never contain '*'
        ("path:/work/*", "path:/WORK/a.txt", False),  # no case folding here; see PathNormalization
    ],
)
def test_prefix_matches(pattern: str, resource: str, expected: bool) -> None:
    assert matches(pattern, resource) is expected


@pytest.mark.parametrize(
    ("parent", "child", "expected"),
    [
        ("path:/work/*", "path:/work/sub/*", True),
        ("path:/work/*", "path:/work/a.txt", True),
        ("path:/work/sub/*", "path:/work/*", False),  # child wider than parent
        ("path:/work/a.txt", "path:/work/a*", False),  # exact parent never covers a prefix child
        ("path:/work/*", "path:*", False),
        ("path:*", "path:/work/*", True),
        ("*", "path:/work/*", True),
        ("path:/work/*", "note:/work/*", False),
    ],
)
def test_prefix_covers(parent: str, child: str, expected: bool) -> None:
    assert covers(parent, child) is expected


@pytest.mark.parametrize("bad", ["path:*/x", "path:a*b", "**", "path:", "path:\x00", "path:/w/**"])
def test_validate_pattern_rejects_misplaced_wildcards(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_pattern(bad)
