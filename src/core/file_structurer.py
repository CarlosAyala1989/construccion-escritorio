import os
import re

class FileStructurer:
    """Módulo de renombrado y estructuración automática de carpetas."""

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
        clean_values = [re.sub(r'[<>:"/\\|?*]', '', str(v)).strip() for v in nomenclature_data.values()]
        
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
