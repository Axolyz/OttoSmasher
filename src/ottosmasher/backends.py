"""Stable public backend identifiers, distinct from checkpoint versions."""

from typing import Literal

PhoneKind = Literal["narabas", "phonetic", "pydomino"]
AnalysisKind = Literal["narabas", "phonetic", "pydomino", "vocals_energy", "acoustic"]
BACKENDS = {
    "narabas": {
        "name": "narabas-v0",
        "version": "narabas-ctc-context-v2",
        "granularity": "phone",
        "env": "inference",
    },
    "phonetic": {"name": "HubertFA", "version": "hubert-context-v4", "granularity": "phone", "env": "inference"},
    "pydomino": {
        "name": "pydomino",
        "version": "pydomino-1.2.1-context-v1",
        "granularity": "phone",
        "env": "inference",
    },
}
DEFAULT_BACKEND = "narabas"
