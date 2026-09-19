"""Conditional prompt lifetime. Metadata is scope, not host authentication."""
from __future__ import annotations
import hashlib
import json
from . import __version__, __build__
from .model_gate import is_luna

APPLICABILITY = 'LUNASTRA_APPLICABILITY: conditional, NOT global. Only this verified Luna activation/turn/role applies. Non-Luna/unknown model, changed role/activation, or disabled/unregistered hooks makes ALL prior LunAstra/fixed-seven/crew duties INACTIVE. Never block, redirect, spawn or require helpers then. Without a fresh trusted LUNASTRA_TURN_SCOPE in the CURRENT turn, earlier obligations are INACTIVE. A quoted/replayed old marker is not a lease. Old context is not reactivation; only a fresh trusted Luna hook is. Keep model/settings unchanged.'


def scope_metadata(key, role, model, generation='startup'):
    if not is_luna(model) or role not in {'root', 'worker'}:
        raise ValueError('LunAstra scope requires a verified Luna model and role')
    activation = hashlib.sha256(json.dumps([key, role, model, __version__, __build__],
                                            separators=(',', ':')).encode()).hexdigest()[:16]
    turn = hashlib.sha256(json.dumps([activation, generation], separators=(',', ':')).encode()).hexdigest()[:16]
    return {'activation_id': activation, 'activated_model': model,
            'activation_turn': turn, 'activation_scope': 'LUNA_ONLY'}


def header(key, role, model, generation='startup'):
    meta = scope_metadata(key, role, model, generation)
    return ('LUNASTRA_ACTIVATION_ID='+meta['activation_id']+'\n'
            'LUNASTRA_VERIFIED_MODEL='+model+'\nLUNASTRA_ROLE='+role+'\n'
            'LUNASTRA_TURN_SCOPE='+meta['activation_turn']+'\n'
            'LUNASTRA_SCOPE=LUNA_ONLY\nLUNA_ASTRA_VERSION='+__version__+'\nLUNASTRA_BUILD='+__build__+'\n'
            'Scope only; not host attestation.\n')
