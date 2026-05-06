"""Создаёт схему и засеивает демо-данные."""
from data.seed import seed
from data.db import DB_PATH


if __name__ == "__main__":
    seed()
    print(f"Database initialised at {DB_PATH}")
