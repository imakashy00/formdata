from datetime import UTC, datetime
import json
import uuid
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.dialects.sqlite.base import SQLiteDDLCompiler
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import Uuid


@compiles(PG_UUID, "sqlite")
def compile_pg_uuid(type_, compiler, **kw):
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def compile_jsonb(type_, compiler, **kw):
    return "JSON"


@compiles(ARRAY, "sqlite")
def compile_array(type_, compiler, **kw):
    return "TEXT"


_orig_array_bind = ARRAY.bind_processor
_orig_array_result = ARRAY.result_processor


def _sqlite_array_bind(self, dialect):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None:
                return json.dumps(value)
            return value
        return process
    return _orig_array_bind(self, dialect)


def _sqlite_array_result(self, dialect, coltype):
    if dialect.name == "sqlite":
        def process(value):
            if value is not None and isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return []
            return value
        return process
    return _orig_array_result(self, dialect, coltype)


ARRAY.bind_processor = _sqlite_array_bind
ARRAY.result_processor = _sqlite_array_result


@compiles(CreateTable, "sqlite")
def compile_create_table_sqlite(element, compiler, **kw):
    old_prefixes = list(element.element._prefixes)
    element.element._prefixes = [p for p in element.element._prefixes if p != "UNLOGGED"]
    try:
        return compiler.visit_create_table(element, **kw)
    finally:
        element.element._prefixes = old_prefixes


_orig_bind_processor = Uuid.bind_processor
_orig_result_processor = Uuid.result_processor


def _sqlite_bind_processor(self, dialect):
    def process(value):
        if value is not None:
            return str(value)
        return value
    return process


def _sqlite_result_processor(self, dialect, coltype):
    def process(value):
        if value is not None:
            if isinstance(value, uuid.UUID):
                return value
            try:
                return uuid.UUID(str(value))
            except Exception:
                return value
        return value
    return process


Uuid.bind_processor = _sqlite_bind_processor
Uuid.result_processor = _sqlite_result_processor

_orig_render_default_string = SQLiteDDLCompiler.render_default_string


def _sqlite_render_default_string(self, default):
    if isinstance(default, str) and "::" in default:
        default = default.split("::")[0].strip()
        if (default.startswith("'") and default.endswith("'")) or (default.startswith('"') and default.endswith('"')):
            default = default[1:-1]
    rendered = _orig_render_default_string(self, default)
    if "::" in rendered:
        rendered = rendered.split("::")[0].strip()
    if rendered.strip().lower() in ("(now())", "now()"):
        rendered = "(CURRENT_TIMESTAMP)"
    return rendered


SQLiteDDLCompiler.render_default_string = _sqlite_render_default_string


def register_sqlite_functions(dbapi_conn):
    dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))
    dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat())
