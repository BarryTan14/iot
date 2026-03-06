import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import re
from pathlib import Path
from paddleocr import PaddleOCR


class OcrEngine:
    def __init__(self, confidence_threshold: float = 0.85) -> None:
        self.confidence_threshold = confidence_threshold
        self.ocr = PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    @staticmethod
    def normalize_plate_text(text: str) -> str:
        return re.sub(r"[^A-Za-z0-9]", "", text).upper()

    @staticmethod
    def looks_like_plate(text: str) -> bool:
        return bool(re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]?", text))

    def process_image(self, image_path: Path) -> dict:
        results = self.ocr.predict(str(image_path))

        best_plate = None
        best_score = -1.0
        all_candidates = []

        for res in results:
            data = res.json
            inner = data.get("res", data)

            rec_texts = inner.get("rec_texts", [])
            rec_scores = inner.get("rec_scores", [])

            for raw_text, raw_score in zip(rec_texts, rec_scores):
                score = float(raw_score)
                normalized = self.normalize_plate_text(raw_text)

                candidate = {
                    "raw_text": raw_text,
                    "normalized": normalized,
                    "confidence": score,
                    "looks_like_plate": self.looks_like_plate(normalized),
                }
                all_candidates.append(candidate)

                if candidate["looks_like_plate"] and score > best_score:
                    best_plate = normalized
                    best_score = score

        should_retry = (best_plate is None) or (best_score < self.confidence_threshold)

        return {
            "plate": best_plate,
            "confidence": best_score if best_plate else None,
            "should_retry": should_retry,
            "all_candidates": all_candidates,
        }