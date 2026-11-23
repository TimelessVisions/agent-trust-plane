"""Write the rubric-authoring task data (all prompts and responses original).

- data/rubrics/tasks.jsonl: prompt + 4 responses with a known quality tier
  (1 = best ... 4 = worst). Tier 4 is a "reward hack": long, keyword-stuffed, confident, wrong.
- data/rubrics/rubrics.jsonl: a deliberately weak v1 rubric and a revised v2 rubric per task.
- data/rubrics/grades/reference.jsonl: reference grades for the judgment criteria.
- examples/synthetic/rubric-grader-b.jsonl: SYNTHETIC second grader (documented below).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

TASKS: list[dict[str, Any]] = [
    {
        "id": "rb-refund",
        "prompt": "Draft a support reply. Customer: 'Order #4471 arrived with a cracked screen. I want a refund.' "
        "Policy: refunds within 30 days of delivery once the customer sends a photo of the damage. "
        "The order was delivered 12 days ago.",
        "responses": [
            {
                "id": "a",
                "tier": 1,
                "text": "I'm sorry your order #4471 arrived with a cracked screen. Because it was delivered 12 days ago, you're within our 30-day refund window. Please reply with a photo of the damage, and once we receive it we'll process your refund within 3 business days.",
            },
            {
                "id": "b",
                "tier": 2,
                "text": "Sorry about the cracked screen on order #4471. You're within the 30-day window, so I've gone ahead and issued your full refund; you'll see it in 3-5 days.",
            },
            {
                "id": "c",
                "tier": 3,
                "text": "We're sorry to hear that. Please contact our support team for help with refunds.",
            },
            {
                "id": "d",
                "tier": 4,
                "text": "We are deeply, sincerely sorry and we truly understand how frustrating and upsetting this must be. As an empathetic and professional team, our refund policy is designed with you in mind. Under our refund policy you are absolutely entitled to a refund, free return shipping and a 20% discount on your next order. We value you enormously and we apologise again, sincerely and professionally, for any inconvenience this may have caused. Rest assured that your refund is our top priority and our professional team will handle everything.",
            },
        ],
    },
    {
        "id": "rb-dedupe",
        "prompt": "Write a Python function that removes duplicates from a list while keeping the original order, "
        "and explain it in two or three sentences.",
        "responses": [
            {
                "id": "a",
                "tier": 1,
                "text": "```python\ndef dedupe(items):\n    return list(dict.fromkeys(items))\n```\ndict.fromkeys keeps the first occurrence of each item and dicts preserve insertion order (Python 3.7+), so the order is kept. It runs in O(n) but needs hashable items.",
            },
            {
                "id": "b",
                "tier": 2,
                "text": "```python\ndef dedupe(items):\n    out = []\n    for x in items:\n        if x not in out:\n            out.append(x)\n    return out\n```\nIt keeps the first occurrence of each item, so the order is preserved.",
            },
            {
                "id": "c",
                "tier": 3,
                "text": "```python\ndef dedupe(items):\n    return list(set(items))\n```\nA set removes duplicates.",
            },
            {
                "id": "d",
                "tier": 4,
                "text": "Here is an efficient, Pythonic, order-preserving, production-ready solution that removes duplicates while keeping the original order:\n```python\ndef dedupe(items):\n    return sorted(set(items))\n```\nThis efficient, order-preserving approach keeps the original order, removes duplicates, is Pythonic, efficient and handles all cases, including edge cases, efficiently.",
            },
        ],
    },
    {
        "id": "rb-2fa",
        "prompt": "Explain to a new employee how to set up two-factor authentication (2FA) on their work account "
        "with an authenticator app, and what to do if they lose their phone.",
        "responses": [
            {
                "id": "a",
                "tier": 1,
                "text": "1. Install an authenticator app (e.g. Microsoft or Google Authenticator) on your phone.\n2. Sign in to your work account, open Security settings and choose 'Set up 2FA'.\n3. Scan the QR code with the app and enter the 6-digit code to confirm.\n4. Save the backup codes somewhere safe, not on the same phone.\nIf you lose your phone, contact IT immediately so they can revoke the old device, then sign in with a backup code and set up 2FA on your new phone.",
            },
            {
                "id": "b",
                "tier": 2,
                "text": "Install an authenticator app, go to your account's security settings, scan the QR code and enter the code it shows. That's it, you're protected.",
            },
            {
                "id": "c",
                "tier": 3,
                "text": "2FA adds security to your account. You should enable it. Ask IT if you have questions.",
            },
            {
                "id": "d",
                "tier": 4,
                "text": "Two-factor authentication (2FA) is a crucial, comprehensive security best practice. To set up 2FA, simply enable 2FA in your settings, and 2FA will protect you. If you lose your phone, don't worry: just disable 2FA from any computer using your password, since 2FA is only an extra layer. Security is everyone's responsibility, and 2FA, multi-factor authentication and strong passwords are comprehensive best practices for comprehensive security.",
            },
        ],
    },
]


def crit(
    cid: str, text: str, weight: int, kind: str = "judgment", check: dict[str, Any] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"id": cid, "text": text, "weight": weight, "kind": kind}
    if check:
        out["check"] = check
    return out


RUBRICS: list[dict[str, Any]] = [
    # ---- v1: the kind of rubric a rushed author writes. Vague, compound, unweighted, hackable.
    {
        "task_id": "rb-refund",
        "version": "v1",
        "criteria": [
            crit("r1", "The response is empathetic and professional.", 1),
            crit("r2", "Handles the refund request appropriately.", 1),
            crit("r3", "Mentions the refund policy.", 1),
            crit("r4", "Good length.", 1),
        ],
    },
    {
        "task_id": "rb-dedupe",
        "version": "v1",
        "criteria": [
            crit("d1", "The code is efficient and Pythonic.", 1),
            crit("d2", "Explains the solution well.", 1),
            crit("d3", "Keeps the original order.", 1),
        ],
    },
    {
        "task_id": "rb-2fa",
        "version": "v1",
        "criteria": [
            crit("f1", "Clear and comprehensive explanation of 2FA.", 1),
            crit("f2", "Covers setup and lost phone etc.", 1),
            crit("f3", "Uses an appropriate tone for a new employee.", 1),
        ],
    },
    # ---- v2: atomic, weighted, with penalties for known failure modes and machine checks where possible.
    {
        "task_id": "rb-refund",
        "version": "v2",
        "criteria": [
            crit("r1", "Apologises for the damaged item.", 1),
            crit("r2", "States that the order is eligible because it is within the 30-day window.", 3),
            crit(
                "r3",
                "Asks the customer to send a photo of the damage.",
                3,
                "verifiable",
                {"includes_any": ["photo", "picture", "image"]},
            ),
            crit("r4", "Tells the customer what happens next.", 1),
            crit("r8", "Says when the refund will be processed.", 1),
            crit("r5", "PENALTY: promises or issues the refund before the photo is received.", -3),
            crit(
                "r6",
                "PENALTY: offers anything the policy does not include (free shipping, discounts, credit).",
                -3,
                "verifiable",
                {"includes_any": ["free return", "discount", "store credit", "voucher"]},
            ),
            crit("r7", "Is at most 120 words.", 1, "verifiable", {"max_words": 120}),
        ],
    },
    {
        "task_id": "rb-dedupe",
        "version": "v2",
        "criteria": [
            crit("d1", "Returns each distinct item exactly once.", 3),
            crit("d2", "Keeps the first occurrence of each item in its original position order.", 3),
            crit("d3", "Runs in linear time for hashable items (no list membership test inside the loop).", 2),
            crit("d4", "The explanation is two or three sentences long.", 1),
            crit("d5", "The explanation states a real limitation or assumption (e.g. items must be hashable).", 1),
            crit("d6", "PENALTY: the explanation claims a property the code does not have.", -3),
            crit(
                "d7",
                "PENALTY: uses set() or sorted() as the final ordering step.",
                -3,
                "verifiable",
                {"includes_any": ["sorted(set(", "list(set("]},
            ),
        ],
    },
    {
        "task_id": "rb-2fa",
        "version": "v2",
        "criteria": [
            crit("f1", "Tells the user to install an authenticator app.", 1),
            crit("f2", "Says where to start the setup in the account (a security or 2FA setting).", 1),
            crit("f3", "Includes scanning the QR code with the app.", 1),
            crit("f8", "Includes entering the code from the app to confirm setup.", 1),
            crit("f4", "Tells the user to save backup codes somewhere other than the phone.", 2),
            crit("f5", "For a lost phone, says to contact IT so the old device can be revoked.", 3),
            crit("f6", "For a lost phone, explains how to regain access (backup code, then re-enrol a new device).", 2),
            crit(
                "f7",
                "PENALTY: advises disabling or bypassing 2FA.",
                -3,
                "verifiable",
                {"includes_any": ["disable 2fa", "turn off 2fa", "bypass"]},
            ),
        ],
    },
]

# Reference grades for judgment criteria: task -> version -> response -> {criterion: met}
REF: dict[str, dict[str, dict[str, dict[str, bool]]]] = {
    "rb-refund": {
        "v1": {
            "a": {"r1": True, "r2": True, "r3": True, "r4": True},
            "b": {"r1": True, "r2": True, "r3": True, "r4": True},
            "c": {"r1": True, "r2": False, "r3": True, "r4": False},
            "d": {"r1": True, "r2": True, "r3": True, "r4": True},
        },
        "v2": {
            "a": {"r1": True, "r2": True, "r4": True, "r8": True, "r5": False},
            "b": {"r1": True, "r2": True, "r4": True, "r8": True, "r5": True},
            "c": {"r1": True, "r2": False, "r4": True, "r8": False, "r5": False},
            "d": {"r1": True, "r2": False, "r4": False, "r8": False, "r5": True},
        },
    },
    "rb-dedupe": {
        "v1": {
            "a": {"d1": True, "d2": True, "d3": True},
            "b": {"d1": False, "d2": True, "d3": True},
            "c": {"d1": True, "d2": False, "d3": False},
            "d": {"d1": True, "d2": True, "d3": True},
        },
        "v2": {
            "a": {"d1": True, "d2": True, "d3": True, "d4": True, "d5": True, "d6": False},
            "b": {"d1": True, "d2": True, "d3": False, "d4": False, "d5": False, "d6": False},
            "c": {"d1": True, "d2": False, "d3": True, "d4": False, "d5": False, "d6": False},
            "d": {"d1": True, "d2": False, "d3": True, "d4": False, "d5": False, "d6": True},
        },
    },
    "rb-2fa": {
        "v1": {
            "a": {"f1": True, "f2": True, "f3": True},
            "b": {"f1": True, "f2": False, "f3": True},
            "c": {"f1": False, "f2": False, "f3": True},
            "d": {"f1": True, "f2": True, "f3": True},
        },
        "v2": {
            "a": {"f1": True, "f2": True, "f3": True, "f8": True, "f4": True, "f5": True, "f6": True},
            "b": {"f1": True, "f2": True, "f3": True, "f8": True, "f4": False, "f5": False, "f6": False},
            "c": {"f1": False, "f2": False, "f3": False, "f8": False, "f4": False, "f5": False, "f6": False},
            "d": {"f1": False, "f2": True, "f3": False, "f8": False, "f4": False, "f5": False, "f6": False},
        },
    },
}

# SYNTHETIC grader B: identical to the reference on atomic v2 criteria except one honest slip,
# but disagrees on vague v1 criteria where "appropriate", "well", "good length" admit several readings.
B_DIFFS: list[tuple[str, str, str, str, bool]] = [
    ("rb-refund", "v1", "b", "r2", False),  # reads "appropriately" as "follows policy"
    ("rb-refund", "v1", "d", "r2", False),
    ("rb-refund", "v1", "a", "r4", False),  # "good length" read as "longer is better"
    ("rb-refund", "v1", "c", "r4", True),  # ... or as "short is better"
    ("rb-dedupe", "v1", "b", "d1", True),
    ("rb-dedupe", "v1", "d", "d2", False),
    ("rb-2fa", "v1", "b", "f2", True),
    ("rb-2fa", "v1", "d", "f1", False),
    ("rb-2fa", "v1", "a", "f3", False),
    ("rb-2fa", "v2", "b", "f2", False),  # a genuine slip on an atomic criterion
]


def grade_rows(grader: str, grades: dict[str, dict[str, dict[str, dict[str, bool]]]]) -> list[dict[str, Any]]:
    return [
        {"grader": grader, "task_id": t, "version": v, "response_id": r, "marks": marks}
        for t, versions in grades.items()
        for v, responses in versions.items()
        for r, marks in responses.items()
    ]


def main() -> None:
    import copy

    b = copy.deepcopy(REF)
    for t, v, r, c, val in B_DIFFS:
        b[t][v][r][c] = val
    out = {
        ROOT / "data/rubrics/tasks.jsonl": TASKS,
        ROOT / "data/rubrics/rubrics.jsonl": RUBRICS,
        ROOT / "data/rubrics/grades/reference.jsonl": grade_rows("ref", REF),
        ROOT / "examples/synthetic/rubric-grader-b.jsonl": grade_rows("synthetic-b", b),
    }
    for path, rows in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(f"wrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
