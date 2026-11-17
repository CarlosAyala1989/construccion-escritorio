# Pruebas automatizadas de desktop authentication.
import unittest

import bcrypt
import pyotp

from src.database.sqlite_manager import AdministradorBaseDatos, ErrorAutenticacion


# Agrupa el comportamiento de fake cursor y el estado de sus operaciones.
class CursorSimulado:
    # Inicializa las dependencias y el estado de esta instancia.
    def __init__(self, user):
        self.user = user

    # Conserva la consulta para que la prueba pueda inspeccionar su resultado.
    def execute(self, query, params):
        self.query = query
        self.params = params

    # Devuelve el único usuario preparado por la prueba.
    def fetchone(self):
        return self.user

    # Cierra close según las reglas del componente.
    def close(self):
        pass


# Agrupa el comportamiento de fake connection y el estado de sus operaciones.
class ConexionSimulada:
    # Inicializa las dependencias y el estado de esta instancia.
    def __init__(self, user):
        self.user = user

    # Crea un cursor aislado para la autenticación simulada.
    def cursor(self, dictionary=False):
        return CursorSimulado(self.user)

    def rollback(self):
        """Imita el cierre de la instantánea de lectura de mysql-connector."""
        return None


# Agrupa el comportamiento de desktop authentication tests y el estado de sus operaciones.
class PruebasAutenticacionEscritorio(unittest.TestCase):
    # Establece up según las reglas del componente.
    def setUp(self):
        self.secret = pyotp.random_base32()
        self.user = {
            "id": "user-id",
            "name": "Desktop User",
            "email": "desktop@example.com",
            "password": bcrypt.hashpw(b"correct-password", bcrypt.gensalt()).decode("utf-8"),
            "role": "EMPLOYEE",
            "isActive": True,
            "accessRole": "DESKTOP_SCANNER",
            "twoFactorEnabled": True,
            "twoFactorSecret": self.secret,
        }

    # Construye el administrador sin abrir SQLite ni MySQL reales.
    def crear_administrador(self, user=None):
        manager = object.__new__(AdministradorBaseDatos)
        connection = ConexionSimulada(self.user if user is None else user)
        manager.obtener_mysql = lambda: connection
        return manager

    # Comprueba accepts valid contraseña and totp mediante una prueba de regresión.
    def test_acepta_contrasena_y_totp_validos(self):
        manager = self.crear_administrador()

        result = manager.autenticar_usuario(
            self.user["email"],
            "correct-password",
            pyotp.TOTP(self.secret).now(),
        )

        self.assertEqual(self.user["id"], result["id"])
        self.assertNotIn("twoFactorSecret", result)

    # Comprueba rejects invalid totp mediante una prueba de regresión.
    def test_rechaza_totp_invalido(self):
        manager = self.crear_administrador()

        with self.assertRaisesRegex(ErrorAutenticacion, "inválido o vencido"):
            manager.autenticar_usuario(
                self.user["email"],
                "correct-password",
                "12345",
            )

    # Comprueba rejects usuario without authenticator mediante una prueba de regresión.
    def test_rechaza_usuario_sin_autenticador(self):
        user = {**self.user, "twoFactorEnabled": False, "twoFactorSecret": None}
        manager = self.crear_administrador(user)

        with self.assertRaisesRegex(ErrorAutenticacion, "no está configurado"):
            manager.autenticar_usuario(
                user["email"],
                "correct-password",
                "123456",
            )


if __name__ == "__main__":
    unittest.main()
