"""PostgreSQL URL forms for the SQLAlchemy and native psycopg clients."""


def postgres_url(value: str, *, sqlalchemy: bool = False) -> str:
    scheme, separator, address = value.partition("://")
    if not separator or not address or scheme not in {
        "postgres", "postgresql", "postgresql+psycopg",
    }:
        raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
    # Keep encoded credentials, IPv6 brackets and repeated connection options intact.
    prefix = "postgresql+psycopg" if sqlalchemy else "postgresql"
    return f"{prefix}://{address}"
