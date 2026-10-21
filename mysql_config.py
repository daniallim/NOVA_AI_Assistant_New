"""
MySQL connection settings for NOVA.

Edit MYSQL_PASSWORD below to match the root password you set when you
installed MySQL Server / MySQL Workbench.

You can also override any value with environment variables, e.g.:
    setx NOVA_MYSQL_PASSWORD "my_password"
"""

import os

MYSQL_HOST = os.getenv("NOVA_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("NOVA_MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("NOVA_MYSQL_USER", "root")

# <<< CHANGE THIS to your MySQL Workbench root password >>>
MYSQL_PASSWORD = os.getenv("NOVA_MYSQL_PASSWORD", "#DataCentre8061")

MYSQL_DATABASE = os.getenv("NOVA_MYSQL_DATABASE", "nova_ai")

# Connection pool size. 5 is plenty for a desktop app.
MYSQL_POOL_SIZE = int(os.getenv("NOVA_MYSQL_POOL_SIZE", "5"))

# The default user row NOVA attaches its data to.
DEFAULT_USER_NAME = os.getenv("NOVA_USER_NAME", "shang")
DEFAULT_USER_EMAIL = os.getenv("NOVA_USER_EMAIL", "shang@localhost")


def connection_kwargs(include_database=True):
    """Keyword args for mysql.connector.connect()."""
    kwargs = {
        "host": MYSQL_HOST,
        "port": MYSQL_PORT,
        "user": MYSQL_USER,
        "password": MYSQL_PASSWORD,
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "autocommit": False,
        "connection_timeout": 10,
    }
    if include_database:
        kwargs["database"] = MYSQL_DATABASE
    return kwargs


def safe_summary():
    """Printable connection info with the password masked."""
    return f"{MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"
