import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import re
from pathlib import Path
from typing import Optional

from paddleocr import PaddleOCR


class OcrEngine:
    def __init__(self) -> None:
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
        # Example matches:
        # S1234A
        # SB1234D
        # E123A
        return bool(re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]?", text))

    def process_image(self, image_path: Path) -> dict:
        results = self.ocr.predict(str(image_path))

        best_plate: Optional[str] = None
        best_score = -1.0

        for res in results:
            data = res.json
            inner = data.get("res", data)

            rec_texts = inner.get("rec_texts", [])
            rec_scores = inner.get("rec_scores", [])

            for raw_text, raw_score in zip(rec_texts, rec_scores):
                normalized = self.normalize_plate_text(raw_text)
                score = float(raw_score)

                if self.looks_like_plate(normalized) and score > best_score:
                    best_plate = normalized
                    best_score = score

        if best_plate is None:
            return {
                "carplate_num": None,
                "confidence_percentage": 0.0,
            }

        return {
            "carplate_num": best_plate,
            "confidence_percentage": round(best_score * 100, 2),
        }