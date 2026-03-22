import sys
import os
from sqlalchemy import text, inspect, String, Enum
from athena.database.db import engine
from athena.core.models import Base


def fix_schema():
    print("Checking database schema for all models...")
    inspector = inspect(engine)

    # Ensure all tables exist
    Base.metadata.create_all(bind=engine)
    print("Base tables checked/created.")

    with engine.connect() as conn:
        for table_name, table in Base.metadata.tables.items():
            try:
                existing_columns = [c['name'] for c in inspector.get_columns(table_name)]
                for col_name, column in table.columns.items():
                    if col_name not in existing_columns:
                        print(f"Adding missing column '{col_name}' to table '{table_name}'...")

                        # Get the column type (e.g. INTEGER, FLOAT, etc.)
                        col_type = column.type.compile(engine.dialect)

                        # Handle defaults
                        default_clause = ""
                        if column.default is not None and hasattr(column.default, 'arg'):
                            arg = column.default.arg
                            if not callable(arg):
                                if isinstance(column.type, Enum):
                                    # Skip default for Enum to avoid quoting/type casting issues
                                    default_clause = ""
                                elif isinstance(column.type, String):
                                    default_clause = f" DEFAULT '{arg}'"
                                else:
                                    default_clause = f" DEFAULT {arg}"

                        alter_query = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}{default_clause}"
                        conn.execute(text(alter_query))
                        conn.commit()
                        print(f"Column '{col_name}' added successfully.")
            except Exception as e:
                print(f"Error checking/updating table '{table_name}': {e}")

    print("Full schema synchronization complete.")


if __name__ == "__main__":
    # Ensure athena is in path
    sys.path.append(os.getcwd())
    fix_schema()
