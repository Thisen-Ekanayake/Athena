import os
import sys
from athena.database.db import engine
from athena.core.models import Base

def main():
    print("Initializing database...")
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully.")

if __name__ == "__main__":
    # Ensure athena is in path
    sys.path.append(os.getcwd())
    main()
