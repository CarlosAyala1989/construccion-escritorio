"""
Vision Engine — Computer Vision / Template Matching con OpenCV.
Fase 3: Seguridad Visual (Marcas de agua, sellos, firmas).
VISUAL tiene prioridad absoluta sobre SEMANTIC.
"""

import os
import cv2
import numpy as np

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Directory for visual template images
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATES_DIR = os.path.join(BASE_DIR, "data", "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)


class VisionEngine:
    """Engine for visual security detection using OpenCV Template Matching."""

    def __init__(self):
        self.templates = {}

    def load_templates(self, visual_policies):
        """
        Load template images for each visual policy.
        Templates should be stored in data/templates/ with the target name.
        """
        self.templates = {}
        for policy in visual_policies:
            if policy.get("type") != "VISUAL":
                continue

            target = policy.get("target", "")
            # Look for template image files
            for ext in [".png", ".jpg", ".jpeg", ".bmp"]:
                template_path = os.path.join(TEMPLATES_DIR, target + ext)
                if os.path.exists(template_path):
                    template_img = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
                    if template_img is not None:
                        self.templates[target] = {
                            "image": template_img,
                            "policy": policy,
                        }
                        print(f"[VISION] Loaded template: {target}")
                    break

    def check_visual_policies(self, image_path, policies=None):
        """
        Check an image/PDF page for visual matches against loaded templates.
        Returns the matching policy with highest priority, or None.
        """
        if not self.templates:
            if policies:
                self.load_templates(policies)
            if not self.templates:
                return None

        # Load the target image
        try:
            target_img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if target_img is None:
                return None
        except Exception as e:
            print(f"[VISION] Failed to load image {image_path}: {e}")
            return None

        matches = []
        for target_name, template_data in self.templates.items():
            template_img = template_data["image"]
            policy = template_data["policy"]

            try:
                # Perform template matching
                result = cv2.matchTemplate(target_img, template_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                # Threshold for a positive match (0.7 = 70% confidence)
                if max_val >= 0.7:
                    matches.append({
                        "policy": policy,
                        "confidence": max_val,
                        "location": max_loc,
                        "target": target_name,
                    })
                    print(f"[VISION] Match found: {target_name} (confidence: {max_val:.2f})")
            except Exception as e:
                print(f"[VISION] Template matching failed for {target_name}: {e}")

        if not matches:
            return None

        # Return highest priority match
        matches.sort(key=lambda m: (m["policy"].get("priority", 0), m["confidence"]), reverse=True)
        return matches[0]["policy"]

    def pdf_page_to_image(self, pdf_path, page_num=0):
        """
        Convert a PDF page to a temporary image for vision analysis.
        Returns the path to the temp image, or None.
        """
        try:
            from PyPDF2 import PdfReader
            # Simple approach: extract images from PDF
            reader = PdfReader(pdf_path)
            if page_num >= len(reader.pages):
                return None

            page = reader.pages[page_num]

            # Try to extract the first image from the page
            if "/XObject" in page["/Resources"]:
                x_objects = page["/Resources"]["/XObject"].get_object()
                for obj_name in x_objects:
                    obj = x_objects[obj_name].get_object()
                    if obj["/Subtype"] == "/Image":
                        # Extract image data
                        data = obj.get_data()
                        temp_path = os.path.join(TEMPLATES_DIR, f"_temp_page_{page_num}.png")

                        width = obj["/Width"]
                        height = obj["/Height"]

                        img = np.frombuffer(data, dtype=np.uint8)
                        try:
                            img = img.reshape((height, width, -1))
                            cv2.imwrite(temp_path, img)
                            return temp_path
                        except Exception:
                            continue
        except Exception as e:
            print(f"[VISION] PDF to image conversion failed: {e}")

        return None

    def check_document(self, file_path, policies):
        """
        Check a document (PDF or image) against visual policies.
        Returns matching policy or None.
        """
        if not policies:
            return None

        visual_policies = [p for p in policies if p.get("type") == "VISUAL"]
        if not visual_policies:
            return None

        self.load_templates(visual_policies)

        # If it's an image file, check directly
        ext = os.path.splitext(file_path)[1].lower()
        if ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]:
            return self.check_visual_policies(file_path)

        # If it's a PDF, convert pages to images and check
        if ext == ".pdf":
            temp_img = self.pdf_page_to_image(file_path, page_num=0)
            if temp_img:
                result = self.check_visual_policies(temp_img)
                # Clean up temp file
                try:
                    os.remove(temp_img)
                except OSError:
                    pass
                return result

        return None
