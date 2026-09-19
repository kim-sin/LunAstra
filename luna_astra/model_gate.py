"""Side-effect-free model authority shared by every hook gate.

Only parsed event.model grants activation. Names in prompts, config, tool lists
or prior conversation context are never authority. Bare gpt-reserve has no
proven Luna-only discriminator in this release and deliberately stays UNKNOWN.
This module imports only the standard library; never import the task engine here.
"""
from __future__ import annotations
import json
import re

MAX_INPUT = 2 * 1024 * 1024
EVENTS = frozenset({'SessionStart', 'SubagentStart', 'UserPromptSubmit', 'PreToolUse',
                    'PostToolUse', 'Stop', 'SubagentStop', 'PostCompact', 'Interrupt'})
LUNA_MODEL = re.compile(r'gpt-\d+(?:\.\d+)*-luna(?:-[a-z0-9][a-z0-9._-]*)?', re.ASCII)
MODEL_TEXT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', re.ASCII)
RESERVE_POLICY = 'UNKNOWN_FAIL_CLOSED_NO_PROVEN_LUNA_DISCRIMINATOR'


def classify(value):
    """Return LUNA / NON_LUNA / UNKNOWN; UNKNOWN never authorizes LunAstra."""
    if not isinstance(value, str) or not MODEL_TEXT.fullmatch(value):
        return 'UNKNOWN'
    if value == 'gpt-reserve':
        return 'UNKNOWN'
    return 'LUNA' if LUNA_MODEL.fullmatch(value) else 'NON_LUNA'


def is_luna(value):
    return classify(value) == 'LUNA'


def accepts_event(event):
    return (isinstance(event, dict) and isinstance(event.get('hook_event_name'), str)
            and event['hook_event_name'] in EVENTS and is_luna(event.get('model')))


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate hook key')
        result[key] = value
    return result


def parse_hook_input(raw):
    """Malformed/oversized/ambiguous input cannot activate or block another model."""
    if not isinstance(raw, bytes) or len(raw) > MAX_INPUT:
        return None
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))
        return value if isinstance(value, dict) else None
    except (ValueError, RecursionError, UnicodeError):
        return None
