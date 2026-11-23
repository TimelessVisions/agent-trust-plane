"""Write data/code/items.jsonl: code-evaluation items. All tasks and code are original.

Each item has a task, one AI-written candidate solution (what the annotator grades),
a trusted reference solution, and test cases. Some candidates are deliberately buggy,
insecure or slow; tests/test_code_items.py proves which ones fail which tests.
"""

from __future__ import annotations

import json
from pathlib import Path


def case(*args: object, expected: object = None, raises: str | None = None) -> dict[str, object]:
    out: dict[str, object] = {"args": list(args)}
    if raises:
        out["raises"] = raises
    else:
        out["expected"] = expected
    return out


ITEMS = [
    {
        "id": "code-001",
        "function": "second_largest",
        "task": "Write `second_largest(nums)` returning the second largest DISTINCT value in a list of ints, or None if there is none.",
        "candidate": "def second_largest(nums):\n    nums = sorted(nums)\n    return nums[-2]\n",
        "explanation": "Sort the list and take the second element from the end.",
        "reference": "def second_largest(nums):\n    d = sorted(set(nums))\n    return d[-2] if len(d) >= 2 else None\n",
        "tests": [
            case([3, 1, 2], expected=2),
            case([5, 5, 3], expected=3),
            case([7], expected=None),
            case([], expected=None),
            case([4, 4], expected=None),
        ],
    },
    {
        "id": "code-002",
        "function": "is_palindrome",
        "task": "Write `is_palindrome(s)` that returns True if `s` reads the same backwards, ignoring case and any non-alphanumeric characters.",
        "candidate": "def is_palindrome(s):\n    s = s.lower()\n    return s == s[::-1]\n",
        "explanation": "Lowercase the string so case doesn't matter, then compare it with its reverse.",
        "reference": "def is_palindrome(s):\n    t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]\n",
        "tests": [
            case("Racecar", expected=True),
            case("A man, a plan, a canal: Panama", expected=True),
            case("hello", expected=False),
            case("", expected=True),
        ],
    },
    {
        "id": "code-003",
        "function": "merge_intervals",
        "task": "Write `merge_intervals(intervals)` that merges overlapping [start, end] intervals (touching ones merge too) and returns them sorted by start.",
        "candidate": (
            "def merge_intervals(intervals):\n    out = []\n    for s, e in intervals:\n"
            "        if out and s <= out[-1][1]:\n            out[-1][1] = max(out[-1][1], e)\n"
            "        else:\n            out.append([s, e])\n    return out\n"
        ),
        "explanation": "Walk through the intervals; if one overlaps the last merged interval, extend it, otherwise start a new one.",
        "reference": (
            "def merge_intervals(intervals):\n    out = []\n    for s, e in sorted(intervals):\n"
            "        if out and s <= out[-1][1]:\n            out[-1][1] = max(out[-1][1], e)\n"
            "        else:\n            out.append([s, e])\n    return out\n"
        ),
        "tests": [
            case([[1, 3], [2, 6], [8, 10]], expected=[[1, 6], [8, 10]]),
            case([[1, 4], [4, 5]], expected=[[1, 5]]),
            case([[8, 10], [1, 3], [2, 6]], expected=[[1, 6], [8, 10]]),
            case([], expected=[]),
        ],
    },
    {
        "id": "code-004",
        "function": "parse_duration",
        "task": "Write `parse_duration(text)` that converts strings like '1h30m', '45s' or '2h5s' into total seconds. Raise ValueError on anything else, including an empty string.",
        "candidate": (
            "import re\n\ndef parse_duration(text):\n"
            "    m = re.fullmatch(r'(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?', text)\n"
            "    if not text or not m:\n        raise ValueError(f'bad duration: {text!r}')\n"
            "    h, mi, s = (int(g) if g else 0 for g in m.groups())\n    return h * 3600 + mi * 60 + s\n"
        ),
        "explanation": "A full-match regex with optional hour, minute and second groups; empty or non-matching input raises ValueError.",
        "reference": (
            "import re\n\ndef parse_duration(text):\n"
            "    m = re.fullmatch(r'(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?', text)\n"
            "    if not text or not m:\n        raise ValueError(text)\n"
            "    h, mi, s = (int(g) if g else 0 for g in m.groups())\n    return h * 3600 + mi * 60 + s\n"
        ),
        "tests": [
            case("1h30m", expected=5400),
            case("45s", expected=45),
            case("2h5s", expected=7205),
            case("", raises="ValueError"),
            case("10x", raises="ValueError"),
            case("1m1h", raises="ValueError"),
        ],
    },
    {
        "id": "code-005",
        "function": "binary_search",
        "task": "Write `binary_search(arr, target)` for a sorted list: return an index of `target`, or -1 if absent.",
        "candidate": (
            "def binary_search(arr, target):\n    lo, hi = 0, len(arr) - 1\n    while lo < hi:\n"
            "        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n"
            "        if arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n"
        ),
        "explanation": "Standard binary search: halve the range until the target is found.",
        "reference": (
            "def binary_search(arr, target):\n    lo, hi = 0, len(arr) - 1\n    while lo <= hi:\n"
            "        mid = (lo + hi) // 2\n        if arr[mid] == target:\n            return mid\n"
            "        if arr[mid] < target:\n            lo = mid + 1\n        else:\n            hi = mid - 1\n    return -1\n"
        ),
        "tests": [
            case([1, 3, 5, 7], 5, expected=2),
            case([1, 3, 5, 7], 7, expected=3),
            case([4], 4, expected=0),
            case([1, 3], 2, expected=-1),
            case([], 1, expected=-1),
        ],
    },
    {
        "id": "code-006",
        "function": "top_words",
        "task": "Write `top_words(text, k)` returning the k most frequent lowercase words as (word, count) pairs, highest count first; break ties alphabetically.",
        "candidate": (
            "from collections import Counter\n\ndef top_words(text, k):\n"
            "    return Counter(text.lower().split()).most_common(k)\n"
        ),
        "explanation": "Counter.most_common already returns the k most frequent words in order.",
        "reference": (
            "from collections import Counter\n\ndef top_words(text, k):\n    c = Counter(text.lower().split())\n"
            "    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]\n"
        ),
        "tests": [
            case("b a b c", 1, expected=[["b", 2]]),
            case("pear apple pear apple fig", 2, expected=[["apple", 2], ["pear", 2]]),
            case("Zed zed alpha", 2, expected=[["zed", 2], ["alpha", 1]]),
        ],
    },
    {
        "id": "code-007",
        "function": "safe_join",
        "task": "Write `safe_join(base, user_path)` that joins a user-supplied relative path onto `base` and raises ValueError if the result would escape `base` (no absolute paths, no '..' escapes). Return the joined path as a string.",
        "candidate": (
            "import os\n\ndef safe_join(base, user_path):\n    if user_path.startswith('/'):\n"
            "        raise ValueError('absolute paths are not allowed')\n    return os.path.join(base, user_path)\n"
        ),
        "explanation": "Rejects absolute paths so the user can only reach files under base.",
        "reference": (
            "import os\n\ndef safe_join(base, user_path):\n    if os.path.isabs(user_path):\n        raise ValueError(user_path)\n"
            "    root = os.path.normpath(base)\n    full = os.path.normpath(os.path.join(root, user_path))\n"
            "    if full != root and not full.startswith(root + os.sep):\n        raise ValueError(user_path)\n    return full\n"
        ),
        "tests": [
            case("/srv/files", "a/b.txt", expected="/srv/files/a/b.txt"),
            case("/srv/files", "/etc/passwd", raises="ValueError"),
            case("/srv/files", "../secret", raises="ValueError"),
            case("/srv/files", "a/../../etc", raises="ValueError"),
        ],
    },
    {
        "id": "code-008",
        "function": "chunk",
        "task": "Write `chunk(items, size)` splitting a list into consecutive lists of length `size` (the last may be shorter). Raise ValueError if size < 1.",
        "candidate": (
            "def chunk(items, size):\n    if size == 0:\n        raise ValueError('size must be >= 1')\n"
            "    return [items[i:i + size] for i in range(0, len(items), size)]\n"
        ),
        "explanation": "Slice the list in steps of `size`; the final slice is automatically shorter. Invalid sizes raise ValueError.",
        "reference": (
            "def chunk(items, size):\n    if size < 1:\n        raise ValueError(size)\n"
            "    return [items[i:i + size] for i in range(0, len(items), size)]\n"
        ),
        "tests": [
            case([1, 2, 3, 4, 5], 2, expected=[[1, 2], [3, 4], [5]]),
            case([], 3, expected=[]),
            case([1], 5, expected=[[1]]),
            case([1, 2], 0, raises="ValueError"),
        ],
    },
    {
        "id": "code-009",
        "function": "two_sum",
        "task": "Write `two_sum(nums, target)` returning indices [i, j] with i < j and nums[i] + nums[j] == target, or None. Inputs can have 100,000+ elements, so aim for linear time.",
        "candidate": (
            "def two_sum(nums, target):\n    for i in range(len(nums)):\n        for j in range(i + 1, len(nums)):\n"
            "            if nums[i] + nums[j] == target:\n                return [i, j]\n    return None\n"
        ),
        "explanation": "Checks every pair, which is simple and always finds the answer if it exists.",
        "reference": (
            "def two_sum(nums, target):\n    seen = {}\n    for j, x in enumerate(nums):\n        if target - x in seen:\n"
            "            return [seen[target - x], j]\n        seen.setdefault(x, j)\n    return None\n"
        ),
        "tests": [
            case([2, 7, 11, 15], 9, expected=[0, 1]),
            case([3, 2, 4], 6, expected=[1, 2]),
            case([1, 2], 7, expected=None),
        ],
    },
    {
        "id": "code-010",
        "function": "moving_average",
        "task": "Write `moving_average(values, k)` returning the list of averages of every window of k consecutive values. Return [] if k > len(values); raise ValueError if k < 1.",
        "candidate": (
            "def moving_average(values, k):\n    if k < 1:\n        raise ValueError('k must be >= 1')\n"
            "    return [sum(values[i:i + k]) / k for i in range(len(values) - k)]\n"
        ),
        "explanation": "Average each window of size k by slicing; one window per starting position.",
        "reference": (
            "def moving_average(values, k):\n    if k < 1:\n        raise ValueError(k)\n"
            "    return [sum(values[i:i + k]) / k for i in range(len(values) - k + 1)]\n"
        ),
        "tests": [
            case([1, 2, 3, 4], 2, expected=[1.5, 2.5, 3.5]),
            case([5, 5], 2, expected=[5.0]),
            case([1, 2], 3, expected=[]),
            case([1], 0, raises="ValueError"),
        ],
    },
]


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "data" / "code" / "items.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in ITEMS), encoding="utf-8")
    print(f"wrote {len(ITEMS)} code items to {out}")


if __name__ == "__main__":
    main()
