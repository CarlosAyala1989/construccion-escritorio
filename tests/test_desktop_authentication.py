# Pruebas automatizadas de desktop authentication.
import unittest

import bcrypt
import pyotp

from src.database.sqlite_manager import AuthenticationError, DatabaseManager


# Agrupa el comportamiento de fake cursor y el estado de sus operaciones.
class FakeCursor:
    # Inicializa las dependencias y el estado de esta instancia.
    def __init__(self, user):
        self.user = user

    # Gestiona execute según las reglas del componente.
    def execute(self, query, params):
        self.query = query
        self.params = params

    # Gestiona fetchone según las reglas del componente.
    def fetchone(self):
        return self.user

    # Cierra close según las reglas del componente.
    def close(self):
        pass


# Agrupa el comportamiento de fake connection y el estado de sus operaciones.
class FakeConnection:
    # Inicializa las dependencias y el estado de esta instancia.
    def __init__(self, user):
        self.user = user

    # Gestiona cursor según las reglas del componente.
    def cursor(self, dictionary=False):
        return FakeCursor(self.user)


# Agrupa el comportamiento de desktop authentication tests y el estado de sus operaciones.
class DesktopAuthenticationTests(unittest.TestCase):
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

    # Gestiona manager según las reglas del componente.
    def make_manager(self, user=None):
        manager = object.__new__(DatabaseManager)
        connection = FakeConnection(self.user if user is None else user)
        manager.get_mysql = lambda: connection
        return manager

    # Comprueba accepts valid contraseña and totp mediante una prueba de regresión.
    def test_accepts_valid_password_and_totp(self):
        manager = self.make_manager()

        result = manager.authenticate_user(
            self.user["email"],
            "correct-password",
            pyotp.TOTP(self.secret).now(),
        )

        self.assertEqual(self.user["id"], result["id"])
        self.assertNotIn("twoFactorSecret", result)

    # Comprueba rejects invalid totp mediante una prueba de regresión.
    def test_rejects_invalid_totp(self):
        manager = self.make_manager()

        with self.assertRaisesRegex(AuthenticationError, "inválido o vencido"):
            manager.authenticate_user(
                self.user["email"],
                "correct-password",
                "12345",
            )

    # Comprueba rejects usuario without authenticator mediante una prueba de regresión.
    def test_rejects_user_without_authenticator(self):
        user = {**self.user, "twoFactorEnabled": False, "twoFactorSecret": None}
        manager = self.make_manager(user)

        with self.assertRaisesRegex(AuthenticationError, "no está configurado"):
            manager.authenticate_user(
                user["email"],
                "correct-password",
                "123456",
            )


if __name__ == "__main__":
    unittest.main()
