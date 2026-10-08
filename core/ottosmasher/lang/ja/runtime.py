"""（任务进程）日语文本前端的运行时：tsqyomi 会话（统一工厂）+ 带用户辞典的 OpenJTalk + 版本（规格 08 §8.2.3 末、14 §14.2）。

所有对齐共享同一次前端结果；前端结果的版本 = 前端算法版本 + 辞典版本 + tsqyomi 版本（+ 库版本）。
"""

from __future__ import annotations

from pathlib import Path

from ...models import registry
from ...models.onnx import Device, Session, create_session
from . import dictionary, frontend, openjtalk


class JaRuntime:
    def __init__(self, models_dir: Path, support_dir: Path, device: Device, dictionary_path: Path | None, dictionary_version: str) -> None:
        path, sha = registry.locate("tsqyomi", "tsqyomi/model.onnx", models_dir, support_dir)
        self.session: Session = create_session("tsqyomi", path, sha, device)
        openjtalk.install_tsqyomi(
            self.session,
            registry.locate("tsqyomi", "tsqyomi/tokenizer.json", models_dir, support_dir),
            registry.locate("tsqyomi", "tsqyomi/metadata.json", models_dir, support_dir),
        )
        self.pj = openjtalk.load()
        self.jtalk = dictionary.jtalk_for(dictionary_path)
        self.versions = {
            "frontend": frontend.FRONTEND_VERSION,
            "dictionary": dictionary_version,
            "tsqyomi": openjtalk.TSQYOMI_VERSION,
            "library": f"pyopenjtalk-plus {openjtalk.PYOPENJTALK_VERSION}",
        }

    def g2p(self, normalized: str) -> list[dict]:
        return list(self.pj.g2p_mapping(normalized, use_tsqyomi=True, normalize_mode="None", jtalk=self.jtalk))

    def analyze(self, text: str) -> frontend.FrontendResult:
        return frontend.analyze(text, self.g2p, self.versions)
