import logging
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

PDF_RENDER_DPI = 200
FIRST_PDF_PAGE = 1
MAX_EXTRACTED_FIELD_LENGTH = 50
GRAYSCALE_LEVELS = 256
GRAYSCALE_MAX_VALUE = GRAYSCALE_LEVELS - 1
WATERMARK_BACKGROUND_MIN = 220
WATERMARK_BACKGROUND_OFFSET = 80
WATERMARK_FOREGROUND_OFFSET = 8
WATERMARK_MIN_FOREGROUND = 128
WATERMARK_RED_DOMINANCE_THRESHOLD = 25
MIN_WATERMARK_PIXELS = 500
WATERMARK_ROTATION_ANGLES = (-45, 45)
WATERMARK_CROP_BORDER = 40
WATERMARK_OCR_PAGE_SEGMENTATION_MODE = 7
MIN_WATERMARK_WORD_LENGTH = 4
WATERMARK_MORPHOLOGY_KERNEL_SIZE = 5


class OCREngine:
    """Motor para extraer texto de PDFs e imágenes."""

    # RF-06 — Configura las herramientas OCR por instancia, sin estado mutable global.
    def __init__(self):
        self.last_text = ""
        self.tesseract_cmd = shutil.which("tesseract")
        self.pdftoppm_cmd = shutil.which("pdftoppm")
        self.language = os.getenv("OCR_LANG", "spa+eng")

    # RF-06 — Acumula texto por página y conserva el OCR visual suplementario.
    def extract_text_from_pdf(self, pdf_path):
        """Extrae texto incrustado y complementa PDFs híbridos con OCR visual."""
        page_texts = []
        if not pdf_path or not os.path.isfile(pdf_path):
            self.last_text = ""
            return ""

        if HAS_PYPDF2:
            try:
                reader = PdfReader(pdf_path)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        page_texts.append(page_text)
            except Exception:
                logging.getLogger(__name__).exception("Falló la extracción de texto incrustado del PDF.")

        try:
            text = "\n".join(page_texts)
            if text.strip():
                # Un PDF híbrido puede combinar texto seleccionable y una etiqueta
                # de seguridad como imagen. El OCR de la primera página la incluye
                # en la evaluación de políticas semánticas.
                visual_text = self._ocr_from_pdf(
                    pdf_path,
                    first_page=FIRST_PDF_PAGE,
                    last_page=FIRST_PDF_PAGE,
                )
                if visual_text.strip():
                    text = f"{text.rstrip()}\n{visual_text.strip()}"
            else:
                # Si el PDF no contiene texto incrustado, aplica OCR a todas sus páginas.
                text = self._ocr_from_pdf(pdf_path)
        except Exception:
            logging.getLogger(__name__).exception("Falló el procesamiento OCR del PDF.")
            text = "\n".join(page_texts)

        self.last_text = text.strip()
        return self.last_text

    # RF-06 — Valida ruta y disponibilidad OCR antes de iniciar el reconocimiento.
    def extract_text_from_image(self, image_path):
        """Extrae texto de una imagen mediante Tesseract OCR."""
        if not image_path or not os.path.isfile(image_path):
            return ""
        if not HAS_PYTESSERACT and not self.tesseract_cmd:
            return ""

        try:
            text = self._ocr_image(image_path)
            self.last_text = text.strip()
            return self.last_text
        except Exception:
            logging.getLogger(__name__).exception("Falló el reconocimiento OCR de la imagen.")
            return ""

    # RF-06 — Usa dependencias y parámetros de OCR configurados por instancia.
    def _ocr_from_pdf(self, pdf_path, first_page=None, last_page=None):
        """Convierte páginas PDF en imágenes y les aplica OCR."""
        if not self.pdftoppm_cmd:
            logging.getLogger(__name__).warning("pdftoppm no está disponible para procesar el PDF.")
            return ""
        if not HAS_PYTESSERACT and not self.tesseract_cmd:
            logging.getLogger(__name__).warning("Tesseract no está disponible para procesar el PDF.")
            return ""

        with tempfile.TemporaryDirectory(prefix="docuzen_ocr_") as tmp_dir:
            output_prefix = os.path.join(tmp_dir, "page")
            cmd = [
                self.pdftoppm_cmd,
                "-r",
                str(PDF_RENDER_DPI),
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

    # RF-06 — Reutiliza el idioma y el ejecutable definidos por esta instancia.
    def _ocr_image(self, image_path, page_segmentation_mode=None):
        """Aplica OCR a una imagen renderizada mediante Python o la CLI de Tesseract."""
        config = ""
        if page_segmentation_mode is not None:
            config = f"--psm {page_segmentation_mode}"

        if HAS_PYTESSERACT:
            img = Image.open(image_path)
            return pytesseract.image_to_string(img, lang=self.language, config=config)

        if self.tesseract_cmd:
            command = [self.tesseract_cmd, image_path, "stdout", "-l", self.language]
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

    # RF-06 — Nombra umbrales de imagen y registra fallos sin imprimirlos.
    def _ocr_watermark(self, image_path):
        """Extrae texto diagonal grande que el OCR normal podría omitir."""
        if not HAS_PYTESSERACT and not self.tesseract_cmd:
            return ""

        try:
            with Image.open(image_path) as source:
                rgb = source.convert("RGB")
                gray = rgb.convert("L")
                histogram = gray.histogram()
                background = max(
                    range(WATERMARK_BACKGROUND_MIN, GRAYSCALE_LEVELS),
                    key=lambda value: histogram[value],
                )
                lower_bound = max(
                    WATERMARK_MIN_FOREGROUND,
                    background - WATERMARK_BACKGROUND_OFFSET,
                )
                upper_bound = max(
                    lower_bound,
                    background - WATERMARK_FOREGROUND_OFFSET,
                )
                lookup = [
                    0 if lower_bound <= value <= upper_bound else GRAYSCALE_MAX_VALUE
                    for value in range(GRAYSCALE_LEVELS)
                ]
                gray_watermark = gray.point(lookup)

                red, green, blue = rgb.split()
                other_channels = ImageChops.lighter(green, blue)
                red_dominance = ImageChops.subtract(red, other_channels)
                red_lookup = [
                    0 if value >= WATERMARK_RED_DOMINANCE_THRESHOLD else GRAYSCALE_MAX_VALUE
                    for value in range(GRAYSCALE_LEVELS)
                ]
                red_watermark = red_dominance.point(red_lookup)

            # Elimina el suavizado fino del texto oscuro y conserva los trazos
            # más gruesos característicos de una marca de agua.
            watermarks = []
            for watermark in (gray_watermark, red_watermark):
                watermark = watermark.filter(
                    ImageFilter.MaxFilter(WATERMARK_MORPHOLOGY_KERNEL_SIZE)
                )
                watermark = watermark.filter(
                    ImageFilter.MinFilter(WATERMARK_MORPHOLOGY_KERNEL_SIZE)
                )
                if watermark.histogram()[0] >= MIN_WATERMARK_PIXELS:
                    watermarks.append(watermark)

            chunks = []
            for mask_index, watermark in enumerate(watermarks):
                for angle in WATERMARK_ROTATION_ANGLES:
                    rotated = watermark.rotate(angle, expand=True, fillcolor=GRAYSCALE_MAX_VALUE)
                    white = Image.new("L", rotated.size, GRAYSCALE_MAX_VALUE)
                    bounds = ImageChops.difference(rotated, white).getbbox()
                    if not bounds:
                        continue

                    candidate = ImageOps.expand(
                        rotated.crop(bounds),
                        border=WATERMARK_CROP_BORDER,
                        fill=GRAYSCALE_MAX_VALUE,
                    )
                    candidate_path = (
                        f"{image_path}.watermark-{mask_index}-{angle}.png"
                    )
                    try:
                        candidate.save(candidate_path)
                        text = self._ocr_image(
                            candidate_path,
                            page_segmentation_mode=WATERMARK_OCR_PAGE_SEGMENTATION_MODE,
                        ).strip()
                        has_word = re.search(
                            rf"[A-ZÁÉÍÓÚÑ]{{{MIN_WATERMARK_WORD_LENGTH},}}",
                            text.upper(),
                        )
                        if text and has_word and text.casefold() not in {
                            chunk.casefold() for chunk in chunks
                        }:
                            chunks.append(text)
                    finally:
                        try:
                            os.remove(candidate_path)
                        except OSError:
                            logging.getLogger(__name__).debug(
                                "No se pudo retirar una imagen temporal de marca de agua.",
                                exc_info=True,
                            )

            return "\n".join(chunks)
        except Exception:
            logging.getLogger(__name__).exception("Falló la extracción OCR de marcas de agua.")
            return ""

    # RF-06 — Limita cada campo con una constante y valida campos requeridos al extraer.
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
            # Busca patrones como «CAMPO: VALOR» o «CAMPO - VALOR».
            patterns = [
                rf'{re.escape(field_name.upper())}\s*[:\-=]\s*([^\n\r]+)',
                rf'{re.escape(field_name.upper())}\s+([A-Z0-9\-_]+)',
            ]

            extracted = None
            for pattern in patterns:
                match = re.search(pattern, text_upper)
                if match:
                    extracted = match.group(1).strip()[:MAX_EXTRACTED_FIELD_LENGTH]
                    break

            if extracted:
                result[field_name] = extracted
            elif field.get("isRequired", True):
                return None

        return result if result else None

    # RF-06
    def extract_title_hierarchy(self, text):
        """Extrae una jerarquía separada por barras de un título INFORME DE RIESGO."""
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

    # RF-07
    def build_filename(self, nomenclature_data, separator="_"):
        """Construye un nombre de archivo a partir de los datos de nomenclatura extraídos."""
        if not nomenclature_data:
            return None
        parts = [str(v) for v in nomenclature_data.values()]
        name = separator.join(parts)
        # Elimina caracteres no válidos en nombres de archivo.
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        return name + ".pdf"

    # RF-10
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
                # Cuenta las palabras del objetivo para ordenarlo.
                word_count = len(target.split())
                is_sentence = word_count > 1
                matches.append({
                    "policy": policy,
                    "word_count": word_count,
                    "is_sentence": is_sentence,
                })

        if not matches:
            return None

        # Ordena primero por mayor cantidad de palabras y luego prioriza frases.
        matches.sort(key=lambda m: (m["word_count"], m["is_sentence"]), reverse=True)
        return matches[0]["policy"]
