import os
import re
import shutil
import subprocess
import tempfile

try:
    import pytesseract
    from PIL import Image, ImageChops, ImageFilter, ImageOps
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False

try:
    from PyPDF2 import PdfReader
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

TESSERACT_CMD = shutil.which("tesseract")
PDFTOPPM_CMD = shutil.which("pdftoppm")
OCR_LANG = os.getenv("OCR_LANG", "spa+eng")


class OCREngine:
    """Engine for text extraction from PDFs and images."""

    def __init__(self):
        self.last_text = ""

    def extract_text_from_pdf(self, pdf_path):
        """Extract embedded text and supplement hybrid PDFs with visual OCR."""
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

        try:
            if text.strip():
                # A hybrid PDF can contain selectable body text plus an image-only
                # security label. OCR the first page as a visual supplement so a
                # label such as "RESERVADO" participates in semantic policies.
                visual_text = self._ocr_from_pdf(
                    pdf_path,
                    first_page=1,
                    last_page=1,
                )
                if visual_text.strip():
                    text = f"{text.rstrip()}\n{visual_text.strip()}"
            else:
                # A PDF without embedded text is probably scanned; OCR every page.
                text = self._ocr_from_pdf(pdf_path)
        except Exception as e:
            print(f"[OCR] Tesseract failed: {e}")

        self.last_text = text.strip()
        return self.last_text

    def extract_text_from_image(self, image_path):
        """Extract text from an image using Tesseract OCR."""
        if not HAS_PYTESSERACT and not TESSERACT_CMD:
            return ""

        try:
            text = self._ocr_image(image_path)
            self.last_text = text.strip()
            return self.last_text
        except Exception as e:
            print(f"[OCR] Image OCR failed: {e}")
            return ""

    def _ocr_from_pdf(self, pdf_path, first_page=None, last_page=None):
        """Convert PDF pages to images and OCR them."""
        if not PDFTOPPM_CMD:
            print("[OCR] pdftoppm not available; install Poppler to OCR scanned PDFs")
            return ""
        if not HAS_PYTESSERACT and not TESSERACT_CMD:
            print("[OCR] Tesseract not available; install pytesseract or tesseract CLI")
            return ""

        with tempfile.TemporaryDirectory(prefix="docuzen_ocr_") as tmp_dir:
            output_prefix = os.path.join(tmp_dir, "page")
            cmd = [
                PDFTOPPM_CMD,
                "-r",
                "200",
                "-png",
            ]
            if first_page is not None:
                cmd.extend(["-f", str(first_page)])
            if last_page is not None:
                cmd.extend(["-l", str(last_page)])
            cmd.extend([pdf_path, output_prefix])
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            page_images = sorted(
                os.path.join(tmp_dir, name)
                for name in os.listdir(tmp_dir)
                if name.startswith("page-") and name.endswith(".png")
            )

            chunks = []
            for image_path in page_images:
                page_text = self._ocr_image(image_path).strip()
                if page_text:
                    chunks.append(page_text)

                watermark_text = self._ocr_watermark(image_path).strip()
                if (
                    watermark_text
                    and watermark_text.casefold() not in page_text.casefold()
                ):
                    chunks.append(watermark_text)

            return "\n".join(chunks)

    def _ocr_image(self, image_path, page_segmentation_mode=None):
        """Run OCR on a rendered image using the Python binding or Tesseract CLI."""
        config = ""
        if page_segmentation_mode is not None:
            config = f"--psm {page_segmentation_mode}"

        if HAS_PYTESSERACT:
            img = Image.open(image_path)
            return pytesseract.image_to_string(img, lang=OCR_LANG, config=config)

        if TESSERACT_CMD:
            command = [TESSERACT_CMD, image_path, "stdout", "-l", OCR_LANG]
            if page_segmentation_mode is not None:
                command.extend(["--psm", str(page_segmentation_mode)])
            result = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return result.stdout

        return ""

    def _ocr_watermark(self, image_path):
        """Extract large diagonal text ignored by normal OCR."""
        if not HAS_PYTESSERACT and not TESSERACT_CMD:
            return ""

        try:
            with Image.open(image_path) as source:
                rgb = source.convert("RGB")
                gray = rgb.convert("L")
                histogram = gray.histogram()
                background = max(
                    range(220, 256),
                    key=lambda value: histogram[value],
                )
                lower_bound = max(128, background - 80)
                upper_bound = max(lower_bound, background - 8)
                lookup = [
                    0 if lower_bound <= value <= upper_bound else 255
                    for value in range(256)
                ]
                gray_watermark = gray.point(lookup)

                red, green, blue = rgb.split()
                other_channels = ImageChops.lighter(green, blue)
                red_dominance = ImageChops.subtract(red, other_channels)
                red_lookup = [
                    0 if value >= 25 else 255
                    for value in range(256)
                ]
                red_watermark = red_dominance.point(red_lookup)

            # Remove the thin antialiasing left by dark body text while preserving
            # the much thicker strokes used by a watermark.
            watermarks = []
            for watermark in (gray_watermark, red_watermark):
                watermark = watermark.filter(ImageFilter.MaxFilter(5))
                watermark = watermark.filter(ImageFilter.MinFilter(5))
                if watermark.histogram()[0] >= 500:
                    watermarks.append(watermark)

            chunks = []
            for mask_index, watermark in enumerate(watermarks):
                for angle in (-45, 45):
                    rotated = watermark.rotate(angle, expand=True, fillcolor=255)
                    white = Image.new("L", rotated.size, 255)
                    bounds = ImageChops.difference(rotated, white).getbbox()
                    if not bounds:
                        continue

                    candidate = ImageOps.expand(
                        rotated.crop(bounds),
                        border=40,
                        fill=255,
                    )
                    candidate_path = (
                        f"{image_path}.watermark-{mask_index}-{angle}.png"
                    )
                    try:
                        candidate.save(candidate_path)
                        text = self._ocr_image(
                            candidate_path,
                            page_segmentation_mode=7,
                        ).strip()
                        has_word = re.search(r"[A-ZÁÉÍÓÚÑ]{4,}", text.upper())
                        if text and has_word and text.casefold() not in {
                            chunk.casefold() for chunk in chunks
                        }:
                            chunks.append(text)
                    finally:
                        try:
                            os.remove(candidate_path)
                        except OSError:
                            pass

            return "\n".join(chunks)
        except Exception as e:
            print(f"[OCR] Watermark OCR failed: {e}")
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
                    extracted = match.group(1).strip()[:50]
                    break

            if extracted:
                result[field_name] = extracted
            elif field.get("isRequired", True):
                return None

        return result if result else None

    def extract_title_hierarchy(self, text):
        """Extract slash-separated hierarchy from an INFORME DE RIESGO title."""
        if not text:
            return None

        match = re.search(
            r"\bINFORME\s+DE\s+RIESGO\s+N\s*[°º]?\s*"
            r"([A-Z0-9]+(?:-[A-Z0-9]+)*"
            r"(?:\s*/\s*[A-Z0-9]+(?:-[A-Z0-9]+)*)+)",
            text.upper(),
        )
        if not match:
            return None

        hierarchy = [
            re.sub(r"\s+", "", segment).strip(" .")
            for segment in re.split(r"\s*/\s*", match.group(1))
        ]
        hierarchy = [segment for segment in hierarchy if segment]
        return hierarchy if len(hierarchy) > 1 else None

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
            target = policy.get("target", "").strip().lower()
            if target and target in text_lower:
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
