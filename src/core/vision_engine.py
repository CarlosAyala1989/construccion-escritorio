"""
Vision Engine — Computer Vision / Template Matching con OpenCV.
Fase 3: Seguridad Visual (Marcas de agua, sellos, firmas).
VISUAL tiene prioridad absoluta sobre SEMANTIC.
"""

# RF-10 — Analiza marcas visuales y devuelve la política coincidente de mayor prioridad.

import logging
import os
import cv2
import numpy as np
from src.app_paths import TEMPLATES_DIR, ensure_runtime_dirs

TEMPLATE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")
SUPPORTED_IMAGE_EXTENSIONS = TEMPLATE_EXTENSIONS + (".tiff",)
VISUAL_MATCH_THRESHOLD = 0.7
FIRST_PDF_PAGE_INDEX = 0

# Directorio de imágenes de plantillas visuales.
ensure_runtime_dirs()


class VisionEngine:
    """Motor de detección de seguridad visual mediante coincidencia de plantillas OpenCV."""

    def __init__(self):
        self.templates = {}

    def load_templates(self, visual_policies):
        """
        Carga imágenes de plantilla para cada política visual.
        Las plantillas deben guardarse en data/templates/ con el nombre del objetivo.
        """
        self.templates = {}
        for policy in visual_policies:
            if policy.get("type") != "VISUAL":
                continue

            target = policy.get("target", "")
            # Busca archivos de imagen de plantilla.
            for ext in TEMPLATE_EXTENSIONS:
                template_path = os.path.join(TEMPLATES_DIR, target + ext)
                if os.path.exists(template_path):
                    template_img = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
                    if template_img is not None:
                        self.templates[target] = {
                            "image": template_img,
                            "policy": policy,
                        }
                        logging.getLogger(__name__).debug("Plantilla visual cargada: %s", target)
                    break

    def check_visual_policies(self, image_path, policies=None):
        """
        Comprueba si una imagen o página PDF coincide con las plantillas cargadas.
        Devuelve la política coincidente de mayor prioridad o None.
        """
        if not self.templates:
            if policies:
                self.load_templates(policies)
            if not self.templates:
                return None

        # Carga la imagen objetivo.
        try:
            target_img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if target_img is None:
                return None
        except cv2.error:
            logging.getLogger(__name__).exception("No se pudo cargar la imagen para análisis visual.")
            return None

        matches = []
        for target_name, template_data in self.templates.items():
            template_img = template_data["image"]
            policy = template_data["policy"]

            try:
                # Busca coincidencias entre las plantillas y la imagen.
                result = cv2.matchTemplate(target_img, template_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                if max_val >= VISUAL_MATCH_THRESHOLD:
                    matches.append({
                        "policy": policy,
                        "confidence": max_val,
                        "location": max_loc,
                        "target": target_name,
                    })
                    logging.getLogger(__name__).debug(
                        "Coincidencia visual %s con confianza %.2f.",
                        target_name,
                        max_val,
                    )
            except cv2.error:
                logging.getLogger(__name__).exception(
                    "Falló la comparación con la plantilla visual %s.",
                    target_name,
                )

        if not matches:
            return None

        # Devuelve la coincidencia de mayor prioridad.
        matches.sort(key=lambda m: (m["policy"].get("priority", 0), m["confidence"]), reverse=True)
        return matches[0]["policy"]

    def pdf_page_to_image(self, pdf_path, page_num=0):
        """
        Convierte una página PDF en una imagen temporal para el análisis visual.
        Devuelve la ruta de la imagen temporal o None.
        """
        if not os.path.isfile(pdf_path):
            return None

        try:
            from PyPDF2 import PdfReader
            # Extrae imágenes del PDF.
            reader = PdfReader(pdf_path)
            if page_num < 0 or page_num >= len(reader.pages):
                return None

            page = reader.pages[page_num]

            # Intenta extraer la primera imagen de la página.
            if "/XObject" in page["/Resources"]:
                x_objects = page["/Resources"]["/XObject"].get_object()
                for obj_name in x_objects:
                    obj = x_objects[obj_name].get_object()
                    if obj["/Subtype"] == "/Image":
                        # Extrae los datos de la imagen.
                        data = obj.get_data()
                        temp_path = os.path.join(TEMPLATES_DIR, f"_temp_page_{page_num}.png")

                        width = obj["/Width"]
                        height = obj["/Height"]

                        img = np.frombuffer(data, dtype=np.uint8)
                        try:
                            img = img.reshape((height, width, -1))
                            if not cv2.imwrite(temp_path, img):
                                raise OSError("OpenCV no pudo escribir la página temporal.")
                            return temp_path
                        except (ValueError, cv2.error, OSError):
                            logging.getLogger(__name__).debug(
                                "No se pudo convertir una imagen incrustada de la página %s.",
                                page_num,
                                exc_info=True,
                            )
                            continue
        except Exception:
            logging.getLogger(__name__).exception("No se pudo convertir la página PDF para análisis visual.")

        return None

    def check_document(self, file_path, policies):
        """
        Compara un documento (PDF o imagen) con las políticas visuales.
        Devuelve la política coincidente o None.
        """
        if not policies:
            return None

        visual_policies = [p for p in policies if p.get("type") == "VISUAL"]
        if not visual_policies:
            return None

        self.load_templates(visual_policies)

        # Si es una imagen, la analiza directamente.
        ext = os.path.splitext(file_path)[1].lower()
        if ext in SUPPORTED_IMAGE_EXTENSIONS:
            return self.check_visual_policies(file_path)

        # Si es un PDF, convierte sus páginas en imágenes y las analiza.
        if ext == ".pdf":
            temp_img = self.pdf_page_to_image(file_path, page_num=FIRST_PDF_PAGE_INDEX)
            if temp_img:
                result = self.check_visual_policies(temp_img)
                # Elimina la imagen temporal.
                try:
                    os.remove(temp_img)
                except OSError:
                    logging.getLogger(__name__).warning(
                        "No se pudo eliminar la imagen temporal del análisis visual.",
                        exc_info=True,
                    )
                return result

        return None
