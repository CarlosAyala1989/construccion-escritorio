"""
OCR Engine — Extracción de texto desde PDFs e imágenes usando Tesseract.
Fase 2: Clasificación Dinámica (Inteligencia Local)
"""

import os
import re

try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False


class OCREngine:
    """Engine for text extraction from PDFs and images."""

    def __init__(self):
        self.last_text = ""

    def extract_text_from_pdf(self, pdf_path):
        """Extract text from a PDF file using PyPDF2 first, Tesseract as fallback."""
        text = ""

        # Try PyPDF2 first (fast, for digital PDFs)
        if HAS_PYPDF2:
            try:
                reader = PdfReader(pdf_path)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            except Exception as e:
                print(f"[OCR] PyPDF2 failed: {e}")

        # If no text extracted, try Tesseract OCR on images
        if not text.strip() and HAS_TESSERACT:
            try:
                text = self._ocr_from_pdf(pdf_path)
            except Exception as e:
                print(f"[OCR] Tesseract failed: {e}")

        self.last_text = text.strip()
        return self.last_text

    def extract_text_from_image(self, image_path):
        """Extract text from an image using Tesseract OCR."""
        if not HAS_TESSERACT:
            return ""
        try:
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang="spa+eng")
            self.last_text = text.strip()
            return self.last_text
        except Exception as e:
            print(f"[OCR] Image OCR failed: {e}")
            return ""

    def _ocr_from_pdf(self, pdf_path):
        """Convert PDF pages to images and OCR them."""
        # Simple fallback: try to use pytesseract on the PDF directly
        try:
            text = pytesseract.image_to_string(pdf_path, lang="spa+eng")
            return text
        except Exception:
            return ""

    def extract_nomenclature(self, text, nomenclature_fields):
        """
        Try to extract nomenclature fields from the OCR text.
        Returns dict of {field_name: extracted_value} or None if failed.
        """
        if not text or not nomenclature_fields:
            return None

        result = {}
        text_upper = text.upper()

        for field in nomenclature_fields:
            field_name = field.get("fieldName", "")
            # Try to find patterns like "FIELD_NAME: VALUE" or "FIELD_NAME - VALUE"
            patterns = [
                rf'{re.escape(field_name.upper())}\s*[:\-=]\s*([^\n\r]+)',
                rf'{re.escape(field_name.upper())}\s+([A-Z0-9\-_]+)',
            ]

            extracted = None
            for pattern in patterns:
                match = re.search(pattern, text_upper)
                if match:
                    extracted = match.group(1).strip()[:50]  # Limit length
                    break

            if extracted:
                result[field_name] = extracted
            elif field.get("isRequired", True):
                return None  # Required field not found → fail

        return result if result else None

    def build_filename(self, nomenclature_data, separator="_"):
        """Build a filename from extracted nomenclature data."""
        if not nomenclature_data:
            return None
        parts = [str(v) for v in nomenclature_data.values()]
        name = separator.join(parts)
        # Clean invalid filename characters
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        return name + ".pdf"

    def check_semantic_policies(self, text, policies):
        """
        Check text against semantic security policies.
        Returns the matching policy with highest priority, or None.
        Implements: sentence match beats word match on tie.
        """
        if not text or not policies:
            return None

        semantic_policies = [p for p in policies if p.get("type") == "SEMANTIC"]
        text_lower = text.lower()

        matches = []
        for policy in semantic_policies:
            target = policy.get("target", "").lower()
            if target in text_lower:
                # Count words in the target for ranking
                word_count = len(target.split())
                is_sentence = word_count > 1
                matches.append({
                    "policy": policy,
                    "word_count": word_count,
                    "is_sentence": is_sentence,
                })

        if not matches:
            return None

        # Sort: more words first, then sentences beat single words
        matches.sort(key=lambda m: (m["word_count"], m["is_sentence"]), reverse=True)
        return matches[0]["policy"]
