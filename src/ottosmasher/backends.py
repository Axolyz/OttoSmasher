"""Stable public backend identifiers, distinct from checkpoint versions."""

from typing import Literal

PhoneKind = Literal["narabas", "phonetic", "pydomino"]
AnalysisKind = Literal["narabas", "phonetic", "pydomino", "vocals_energy", "acoustic"]
BACKENDS = {
    "narabas": {
        "name": "narabas-v0",
        "version": "narabas-ctc-context-v3",
        "granularity": "phone",
        "env": "onnx",
    },
    "phonetic": {"name": "HubertFA", "version": "hubert-context-v5", "granularity": "phone", "env": "onnx"},
    "pydomino": {
        "name": "pydomino",
        "version": "pydomino-1.2.1-context-v2",
        "granularity": "phone",
        "env": "onnx",
    },
}
DEFAULT_BACKEND = "narabas"
