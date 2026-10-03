#!/usr/bin/env python3
"""
Genera el archivo .env exclusivo del instalador en línea de Windows.

El archivo generado se llama .env intencionalmente para que gitignore lo excluya
del repositorio y no se confirme por accidente.
"""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MONOREPO_ROOT = PROJECT_ROOT.parent
OUTPUT = PROJECT_ROOT / "installer" / ".env"

SOURCE_FILES = [
    MONOREPO_ROOT / "construccion-web" / ".env",
    MONOREPO_ROOT / "construccion-web" / ".env.local",
    MONOREPO_ROOT / ".env",
    PROJECT_ROOT / ".env",
]

DATABASE_KEYS = {
    "DATABASE_URL",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
}


def parse_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value

    return values


def main() -> int:
    env_values = {}
    for source_file in SOURCE_FILES:
        env_values.update(parse_env(source_file))

    selected = {key: env_values[key] for key in DATABASE_KEYS if env_values.get(key)}

    if "DATABASE_URL" not in selected:
        required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE"]
        missing = [key for key in required if key not in selected]
        if missing:
            raise SystemExit(
                "No se encontro configuracion MySQL suficiente para el instalador. "
                f"Faltan: {', '.join(missing)}"
            )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generado por scripts/prepare-installer-env.py",
        "# Se instala en %LOCALAPPDATA%\\GobernanzaDocumental\\data\\.env",
    ]
    for key in sorted(selected):
        lines.append(f"{key}={selected[key]}")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Installer database env generated: {OUTPUT}")
    print(f"Included keys: {', '.join(sorted(selected))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
