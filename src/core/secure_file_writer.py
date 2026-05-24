import os
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

class SecureFileWriter:
    """
    CP-057, CP-058: SecureFileWriter cifra con AES-256 en escritura.
    Ningún archivo en claro en el directorio temporal.
    """
    _session_key = get_random_bytes(32)  # Clave AES-256 derivada de sesión

    @classmethod
    def write_secure(cls, source_path, dest_path):
        """Cifra el archivo desde source_path hacia dest_path."""
        with open(source_path, "rb") as f:
            data = f.read()
            
        cipher = AES.new(cls._session_key, AES.MODE_GCM)
        ciphertext, tag = cipher.encrypt_and_digest(data)
        
        with open(dest_path, "wb") as f:
            f.write(cipher.nonce)
            f.write(tag)
            f.write(ciphertext)

    @classmethod
    def read_secure(cls, file_path):
        """Descifra el archivo de file_path y retorna los bytes en claro (para memoria)."""
        with open(file_path, "rb") as f:
            nonce = f.read(16)
            tag = f.read(16)
            ciphertext = f.read()
            
        cipher = AES.new(cls._session_key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt_and_verify(ciphertext, tag)
