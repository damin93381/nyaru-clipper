from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from app.services.subtitles import SubtitleSegment


def _load_transformers_module():
    return importlib.import_module("transformers")


def _load_torch_module():
    return importlib.import_module("torch")


@dataclass(slots=True)
class HuggingFaceTranslationProvider:
    model_name: str
    device: str
    source_language_code: str
    target_language_code: str
    max_new_tokens: int = 256
    _tokenizer: object | None = field(default=None, init=False, repr=False)
    _model: object | None = field(default=None, init=False, repr=False)

    @property
    def metadata(self) -> dict[str, str | int]:
        return {
            "provider": "hf",
            "model_name": self.model_name,
            "device": self.device,
            "source_language_code": self.source_language_code,
            "target_language_code": self.target_language_code,
            "max_new_tokens": self.max_new_tokens,
        }

    def _ensure_runtime(self):
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model

        transformers = _load_transformers_module()
        tokenizer = transformers.AutoTokenizer.from_pretrained(self.model_name)
        model = transformers.AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
        model = model.to(self.device)
        tokenizer.src_lang = self.source_language_code
        self._tokenizer = tokenizer
        self._model = model
        return tokenizer, model

    def translate_segments(self, segments: list[SubtitleSegment]) -> list[str]:
        tokenizer, model = self._ensure_runtime()
        torch = _load_torch_module()

        translated: list[str] = []
        for segment in segments:
            encoded_inputs = tokenizer(segment.text, return_tensors="pt")
            moved_inputs = {
                key: value.to(self.device) if hasattr(value, "to") else value
                for key, value in encoded_inputs.items()
            }
            with torch.inference_mode():
                generated_tokens = model.generate(
                    **moved_inputs,
                    forced_bos_token_id=tokenizer.lang_code_to_id[self.target_language_code],
                    max_new_tokens=self.max_new_tokens,
                )
            translated.append(tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0].strip())
        return translated
