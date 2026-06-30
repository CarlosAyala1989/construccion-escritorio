import os
import re

class FileStructurer:
    """Módulo de renombrado y estructuración automática de carpetas."""

    @staticmethod
    def _clean_path_value(value):
        cleaned = re.sub(r'[<>:"/\\|?*]', '', str(value)).strip().strip(".")
        return cleaned if cleaned not in {"", ".", ".."} else None

    @staticmethod
    def RenameAndStructure(nomenclature_data, base_output_dir, separator="_"):
        """
        CP-022: RenameAndStructure() genera nombre y ruta correctos.
        CP-023: estructura de carpetas automática según jerarquía.
        Construye la ruta de directorios basándose en los valores de la nomenclatura
        y devuelve la ruta completa del nuevo archivo (sin crearlo en disco aún, 
        para que se use como path destino del cifrado/copia).
        """
        if not nomenclature_data:
            return None

        # Clean values
        clean_values = [
            FileStructurer._clean_path_value(value)
            for value in nomenclature_data.values()
        ]
        clean_values = [value for value in clean_values if value]
        
        if not clean_values:
            return None

        # Build folder hierarchy using all but the last field
        if len(clean_values) > 1:
            folder_hierarchy = clean_values[:-1]
            folder_path = os.path.join(base_output_dir, *folder_hierarchy)
        else:
            folder_path = base_output_dir
            
        # Ensure the directory exists
        os.makedirs(folder_path, exist_ok=True)
        
        # Generate filename
        filename = separator.join(clean_values) + ".pdf" # Assuming final output is PDF after crypto/OCR
        
        return os.path.join(folder_path, filename)

    @staticmethod
    def structure_title_hierarchy(hierarchy, base_output_dir):
        """Create title-derived folders and use only the final segment as filename."""
        if not hierarchy:
            return None

        clean_values = [
            FileStructurer._clean_path_value(value)
            for value in hierarchy
        ]
        if any(value is None for value in clean_values):
            return None

        folder_path = os.path.join(base_output_dir, *clean_values[:-1])
        os.makedirs(folder_path, exist_ok=True)
        return os.path.join(folder_path, clean_values[-1] + ".pdf")
