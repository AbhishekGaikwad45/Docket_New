import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _flag(name, default="false"):
    return os.getenv(name, default).lower() in ("1", "true", "yes")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'docket.db'}")

    COMPANY_NAME = os.getenv("COMPANY_NAME", "JSW Jaigarh Port Ltd.")
    # Optional announcement pill on the home page (like the COVID notice in the old portal).
    BANNER_TEXT = os.getenv("BANNER_TEXT", "")
    BANNER_URL = os.getenv("BANNER_URL", "")

    CSRF_ENABLED = True

    # Employee login is an emailed OTP. When mail can't be delivered and this is on,
    # the OTP is shown on screen. Development only - never enable in production.
    OTP_TTL_SECONDS = 300
    OTP_SHOW_ON_SCREEN = _flag("OTP_SHOW_ON_SCREEN")

    SMTP_SERVER = os.getenv("SMTP_SERVER", "")  # empty = mail is only logged
    SMTP_PORT = int(os.getenv("SMTP_PORT", "25"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = _flag("SMTP_USE_TLS")
    SMTP_SENDER = os.getenv("SMTP_SENDER", "docket@localhost")

    # Employee master source (Mantra SQL Server). Full pyodbc connection string or SOURCE_DB_* components.
    SOURCE_ODBC = os.getenv("SOURCE_ODBC", "").strip("\"' ")
    if not SOURCE_ODBC or ("SERVER=" not in SOURCE_ODBC.upper() and "DSN=" not in SOURCE_ODBC.upper()):
        if os.getenv("SOURCE_DB_SERVER"):
            _driver = os.getenv("SOURCE_DB_DRIVER", "SQL Server")
            _server = os.getenv("SOURCE_DB_SERVER")
            _port = os.getenv("SOURCE_DB_PORT", "1433")
            _dbname = os.getenv("SOURCE_DB_NAME", "")
            _user = os.getenv("SOURCE_DB_USER", "")
            _pwd = os.getenv("SOURCE_DB_PASSWORD", "")
            _server_str = f"{_server},{_port}" if _port else _server
            _parts = [f"DRIVER={{{_driver}}}", f"SERVER={_server_str}", f"DATABASE={_dbname}"]
            if _flag("SOURCE_DB_TRUSTED_CONNECTION"):
                _parts.append("Trusted_Connection=yes")
            else:
                if _user:
                    _parts.append(f"UID={_user}")
                if _pwd:
                    _parts.append(f"PWD={_pwd}")
            SOURCE_ODBC = ";".join(_parts)
    # view name -> source label stored on the employee. Staff wins over associates on conflicts.
    SOURCE_VIEWS = {
        "view_EmployeeMaster_Report_Staff": "staff",
        "view_EmployeeMaster_Report_Associates": "associates",
    }
