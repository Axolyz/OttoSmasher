"""Single, versioned Japanese front-end result, before model-specific adapters."""

from __future__ import annotations

import csv
import hashlib
import json
import unicodedata
from pathlib import Path

from .workspace import ROOT, identity

VERSION = "openjtalk-plus-tsqyomi-v1"
MODEL = {
    "repository": "tsukumijima/tsqyomi-models",
    "revision": "680596dd2ad2bad59ee5db3741e197cfce79f9b4",
    "files": ["model.onnx", "tokenizer.json", "metadata.json"],
    "subdirectory": "v4",
}
_initialized = False
_dictionary = None


def normalize_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("对齐文本不能为空")
    # Preserve one code point per original position. Collapse pauses only in the
    # phone record, so caller text spans remain exact and independently editable.
    return "".join(
        "ー" if c in "～〜~" else "、" if c.isspace() or unicodedata.category(c).startswith("P") else c
        for c in text
    )


def mora_text(pron):
    result = []
    for c in pron:
        if c in "ァィゥェォャュョヮ" and result:
            result[-1] += c
        elif "ァ" <= c <= "ヺ" or c == "ー":
            result.append(c)
    return result


def initialize(dictionary=None):
    global _initialized, _dictionary
    import pyopenjtalk

    if not _initialized:
        from pyopenjtalk import tsqyomi

        from .model_inventory import install_support

        install_support()
        folder = ROOT / "models/tsqyomi"
        if not (folder / "preparation.json").is_file():
            raise ValueError("tsqyomi 尚未准备，请先运行 scripts/prepare_tsqyomi.py")
        manifest = json.loads((folder / "preparation.json").read_text())
        if manifest.get("revision") != MODEL["revision"]:
            raise ValueError("tsqyomi 模型版本不匹配")
        for filename, digest in manifest["sha256"].items():
            if (
                filename not in MODEL["files"]
                or hashlib.sha256((folder / filename).read_bytes()).hexdigest() != digest
            ):
                raise ValueError("tsqyomi 模型指纹不匹配")
        if set(manifest["sha256"]) != set(MODEL["files"]):
            raise ValueError("tsqyomi 准备记录不完整")
        # Supply our session without changing the process-global onnxruntime module.
        from pyopenjtalk.tsqyomi import model as tm
        from .inference_runtime import onnx_session, onnx_providers

        def load_local(model_path, tokenizer_path, metadata_path, onnx_providers, allow_provider_fallback):
            from tokenizers import Tokenizer

            metadata = tm.TsqyomiMetadata.load(metadata_path)
            tokenizer = Tokenizer.from_file(str(tokenizer_path))
            tokenizer.no_truncation()
            tokenizer.no_padding()
            session = onnx_session(model_path)
            tm.TsqyomiModel.validate_onnx_contract(session, metadata)
            return tm.TsqyomiModel(tokenizer, session, metadata)

        tm._load_model_from_paths = load_local
        tsqyomi.load_model(model_dir=folder, onnx_providers=onnx_providers(), allow_provider_fallback=False)
        _initialized = True
    if dictionary != _dictionary:
        if dictionary:
            path = Path(dictionary)
            if not path.is_file():
                raise ValueError("冻结的用户辞典版本缺失")
            pyopenjtalk.update_global_jtalk_with_user_dict(
                [{"dic_path": str(path), "is_reading_protected": True}]
            )
        else:
            pyopenjtalk.unset_user_dict()
        _dictionary = dictionary


def generate(text, *, dictionary=None, mapping_function=None):
    normalized = normalize_text(text)
    if mapping_function is None:
        initialize(dictionary)
        import pyopenjtalk

        mapping_function = lambda value: pyopenjtalk.g2p_mapping(
            value, use_tsqyomi=True, normalize_mode="None"
        )
    mappings = mapping_function(normalized)
    phones = []
    owners = []
    moras = []
    word_by_mora = {}
    for token in mappings:
        raw = token["phonemes"]
        parts = mora_text(token.get("pron", ""))
        nuclei = sum(p in {"a", "i", "u", "e", "o", "A", "I", "U", "E", "O", "N", "cl"} for p in raw)
        mapped = nuclei == token.get("mora_count", 0) == len(parts)
        start_index = len(moras)
        moras.extend(parts)
        at = start_index
        for phone in raw:
            if phone in {"pau", "sil", "sp", "SP"}:
                if not phones or phones[-1] != "pau":
                    phones.append("pau")
                    owners.append(None)
                continue
            phones.append(phone)
            owners.append(at if mapped else None)
            if mapped:
                span = token["char_span"]
                word_by_mora[str(at)] = {
                    "word": text[span[0] : span[1]],
                    "text_range": span,
                    "reading": token.get("pron", ""),
                }
            if phone in {"a", "i", "u", "e", "o", "A", "I", "U", "E", "O", "N", "cl"}:
                at += 1
    result = {
        "version": VERSION,
        "text": text,
        "normalized_text": normalized,
        "dictionary": dictionary,
        "tsqyomi": MODEL,
        "phones": phones,
        "phone_mora": owners,
        "mapping": mappings,
        "mora": {
            "reading": "".join(moras),
            "sequence": moras,
            "count": len(moras),
            "source": VERSION,
            "phone_mapping": "same_frontend_result",
            "words": word_by_mora,
        },
    }
    result["signature"] = identity(result)
    return result


def dictionary_entries(text):
    entries = []
    seen = set()
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError(f"第 {i} 行：需要 表记<Tab>片假名发音")
        surface, pron = [p.strip() for p in parts]
        if not surface or surface in seen or len(surface) > 200:
            raise ValueError(f"第 {i} 行：表记为空、重复或过长")
        if not pron or len(pron) > 200 or any(not ("ァ" <= c <= "ヺ" or c == "ー") for c in pron):
            raise ValueError(f"第 {i} 行：发音必须是片假名或长音记号")
        entries.append((surface, pron))
        seen.add(surface)
    return entries


def compile_dictionary(text, folder):
    import pyopenjtalk

    entries = dictionary_entries(text)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    version = identity("user-dictionary-v1", entries)
    csv_path, binary = folder / (version + ".csv"), folder / (version + ".dic")
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        for surface, pron in entries:
            writer.writerow(
                [
                    surface,
                    "",
                    "",
                    1,
                    "名詞",
                    "一般",
                    "*",
                    "*",
                    "*",
                    "*",
                    surface,
                    pron,
                    pron,
                    f"0/{len(mora_text(pron))}",
                    "*",
                ]
            )
    if entries and not binary.exists():
        import uuid

        temporary = folder / (version + "." + uuid.uuid4().hex + ".tmp.dic")
        pyopenjtalk.mecab_dict_index(str(csv_path), str(temporary))
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError("辞典编译未产生有效结果")
        # Load before publishing; a failed compile never changes the active file.
        pyopenjtalk.update_global_jtalk_with_user_dict(
            [{"dic_path": str(temporary), "is_reading_protected": True}]
        )
        temporary.replace(binary)
    return {
        "version": version,
        "path": str(binary) if entries else None,
        "text": text,
        "entries": len(entries),
    }
