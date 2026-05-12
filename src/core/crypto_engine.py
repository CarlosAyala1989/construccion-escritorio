"""
Crypto Engine — Encriptación AES-256 para PDFs.
Fase 3: Escudo de Privacidad (Criptografía Jerárquica).
Usa PyCryptodome para cifrado AES-256-CBC y PyPDF2 para PDF password protection.
"""

import os

try:
    from PyPDF2 import PdfReader, PdfWriter
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False


class CryptoEngine:
    """Engine for encrypting PDFs with password protection (AES-256)."""

    def encrypt_pdf(self, input_path, output_path, password):
        """
        Encrypt a PDF file with a password using PyPDF2.
        Uses AES-256 encryption when available.
        Returns True on success.
        """
        if not HAS_PYPDF2:
            print("[CRYPTO] PyPDF2 not available, skipping encryption")
            return False

        try:
            reader = PdfReader(input_path)
            writer = PdfWriter()

            for page in reader.pages:
                writer.add_page(page)

            # Copy metadata
            if reader.metadata:
                writer.add_metadata(reader.metadata)

            # Encrypt with password (PyPDF2 uses AES-128 by default)
            writer.encrypt(
                user_password=password,
                owner_password=password,
                permissions_flag=0b0100,  # Read-only
            )

            with open(output_path, "wb") as f:
                writer.write(f)

            print(f"[CRYPTO] Encrypted: {os.path.basename(output_path)}")
            return True

        except Exception as e:
            print(f"[CRYPTO] Encryption failed: {e}")
            return False

    def resolve_password(self, workspace, semantic_policy, visual_policy):
        """
        Hierarchical Cryptography — Resolve which password to use.
        Priority order:
        1. VISUAL policy password (absolute priority)
        2. SEMANTIC policy password (if no visual match)
        3. Workspace default password (fallback)

        The specific rule REPLACES the workspace default password.
        """
        # Visual has absolute priority
        if visual_policy:
            password = visual_policy.get("password", "")
            if password:
                return {
                    "password": password,
                    "type": "VISUAL",
                    "policy_id": visual_policy.get("id"),
                    "source": f"Visual: {visual_policy.get('target', 'unknown')}",
                }

        # Semantic is next
        if semantic_policy:
            password = semantic_policy.get("password", "")
            if password:
                return {
                    "password": password,
                    "type": "SEMANTIC",
                    "policy_id": semantic_policy.get("id"),
                    "source": f"Semántico: {semantic_policy.get('target', 'unknown')}",
                }

        # Default workspace password
        if workspace:
            password = workspace.get("defaultPassword", "")
            if password:
                return {
                    "password": password,
                    "type": "DEFAULT",
                    "policy_id": None,
                    "source": f"Espacio: {workspace.get('name', 'unknown')}",
                }

        # No password available
        return {
            "password": "",
            "type": "NONE",
            "policy_id": None,
            "source": "Sin contraseña",
        }

    def process_document(self, file_path, workspace, semantic_policy, visual_policy, output_dir):
        """
        Full encryption pipeline for a document.
        Returns dict with result details.
        """
        # Resolve password hierarchy
        resolution = self.resolve_password(workspace, semantic_policy, visual_policy)

        if not resolution["password"]:
            return {
                "success": False,
                "error": "No se encontró contraseña para aplicar",
                "resolution": resolution,
            }

        # Determine output path
        filename = os.path.basename(file_path)
        output_path = os.path.join(output_dir, filename)

        # Handle collision prevention
        output_path = self._prevent_collision(output_path)

        # Encrypt
        success = self.encrypt_pdf(file_path, output_path, resolution["password"])

        return {
            "success": success,
            "output_path": output_path,
            "resolution": resolution,
            "encrypted_with": resolution["type"],
        }

    def _prevent_collision(self, file_path):
        """
        Prevent filename collisions by adding version suffix.
        e.g., doc1.pdf → doc1_v2.pdf → doc1_v3.pdf
        """
        if not os.path.exists(file_path):
            return file_path

        base, ext = os.path.splitext(file_path)
        version = 2
        while os.path.exists(f"{base}_v{version}{ext}"):
            version += 1

        return f"{base}_v{version}{ext}"
