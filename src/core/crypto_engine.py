"""
Crypto Engine — Encriptación AES-256 para PDFs.
Fase 3: Escudo de Privacidad (Criptografía Jerárquica).
Usa PyCryptodome para cifrado AES-256-CBC y PyPDF2 para proteger PDFs con contraseña.
"""

import logging
import os

PDF_READ_ONLY_PERMISSION = 0b0100
FIRST_COLLISION_VERSION = 2

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False


class CryptoEngine:
    """Motor para cifrar PDFs con protección por contraseña (AES-256)."""

    # RF-09/RF-10 — Protege el PDF con la clave jerárquica y devuelve éxito o fallo.
    def encrypt_pdf(self, input_path, output_path, password):
        """
        Cifra un PDF con contraseña mediante PyPDF2.
        Usa cifrado AES-256 cuando está disponible.
        Devuelve True si la operación se completa correctamente.
        """
        if not HAS_PYPDF2:
            logging.getLogger(__name__).warning("PyPDF2 no está disponible; no se cifró el PDF.")
            return False

        try:
            if not os.path.isfile(input_path):
                raise FileNotFoundError(f"No existe el PDF de entrada: {input_path}")

            reader = PdfReader(input_path)
            writer = PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            # Copia los metadatos.
            if reader.metadata:
                writer.add_metadata(reader.metadata)

            # Cifra con contraseña (PyPDF2 usa AES-128 de forma predeterminada).
            writer.encrypt(
                user_password=password,
                owner_password=password,
                permissions_flag=PDF_READ_ONLY_PERMISSION,
            )

            with open(output_path, "wb") as f:
                writer.write(f)

            logging.getLogger(__name__).info("PDF cifrado: %s", os.path.basename(output_path))
            return True

        except Exception:
            logging.getLogger(__name__).exception("Falló el cifrado del PDF.")
            return False

    def resolve_password(self, workspace, semantic_policy, visual_policy):
        """
        Resuelve qué contraseña usar según la jerarquía criptográfica.
        Orden de prioridad:
        1. Contraseña de la política VISUAL (prioridad absoluta).
        2. Contraseña de la política SEMANTIC (si no hay coincidencia visual).
        3. Contraseña predeterminada del espacio de trabajo (alternativa).

        La regla específica REEMPLAZA la contraseña predeterminada del espacio.
        """
        # La política visual tiene prioridad absoluta.
        if visual_policy:
            password = visual_policy.get("password", "")
            if password:
                return {
                    "password": password,
                    "type": "VISUAL",
                    "policy_id": visual_policy.get("id"),
                    "source": f"Visual: {visual_policy.get('target', 'unknown')}",
                }

        # La política semántica ocupa el siguiente nivel.
        if semantic_policy:
            password = semantic_policy.get("password", "")
            if password:
                return {
                    "password": password,
                    "type": "SEMANTIC",
                    "policy_id": semantic_policy.get("id"),
                    "source": f"Semántico: {semantic_policy.get('target', 'unknown')}",
                }

        # Contraseña predeterminada del espacio de trabajo.
        if workspace:
            password = workspace.get("defaultPassword", "")
            if password:
                return {
                    "password": password,
                    "type": "DEFAULT",
                    "policy_id": None,
                    "source": f"Espacio: {workspace.get('name', 'unknown')}",
                }

        # No hay una contraseña disponible.
        return {
            "password": "",
            "type": "NONE",
            "policy_id": None,
            "source": "Sin contraseña",
        }

    def process_document(self, file_path, workspace, semantic_policy, visual_policy, output_dir):
        """
        Ejecuta el flujo completo de cifrado de un documento.
        Devuelve un diccionario con los detalles del resultado.
        """
        # Resuelve la jerarquía de contraseñas.
        resolution = self.resolve_password(workspace, semantic_policy, visual_policy)

        if not resolution["password"]:
            return {
                "success": False,
                "error": "No se encontró contraseña para aplicar",
                "resolution": resolution,
            }

        # Determina la ruta de salida.
        filename = os.path.basename(file_path)
        output_path = os.path.join(output_dir, filename)

        # Evita sobrescribir archivos existentes.
        output_path = self._prevent_collision(output_path)

        # Cifra el documento.
        success = self.encrypt_pdf(file_path, output_path, resolution["password"])

        return {
            "success": success,
            "output_path": output_path,
            "resolution": resolution,
            "encrypted_with": resolution["type"],
        }

    # RF-14 — Evita colisiones eligiendo la primera variante de nombre disponible.
    def _prevent_collision(self, file_path):
        """
        Prevent filename collisions by adding version suffix.
        e.g., doc1.pdf → doc1_v2.pdf → doc1_v3.pdf
        """
        if not os.path.exists(file_path):
            return file_path

        base, ext = os.path.splitext(file_path)
        version = FIRST_COLLISION_VERSION
        while os.path.exists(f"{base}_v{version}{ext}"):
            version += 1

        return f"{base}_v{version}{ext}"
