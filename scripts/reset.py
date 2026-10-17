"""
This script will deleter the db file to ~reset~ after you've applied new filters HOWEVER due to the way KPMG's career sight works and lists fake dates it will preserve its records to allow some sembilence of date tracking for them.
"""

import sqlite3
from pathlib import Path

from ats_mesh.config import DB_PATH

DB = DB_PATH


def table_names():
    with sqlite3.connect(DB) as con:
        tables = con.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
        """).fetchall()

        print([table[0] for table in tables])


def field_names():
    with sqlite3.connect(DB) as con:
        fields = con.execute("""
        PRAGMA table_info(jobs)
        """).fetchall()

        print([field[1] for field in fields])

        return fields


def company_names():
    with sqlite3.connect(DB) as con:
        companies = con.execute("""
            SELECT DISTINCT company_name
            FROM jobs;
        """).fetchall()
        print(f"{companies}")


def copy_db_with_kpmg():
    company = "KPMG"
    new_db = Path.home() / "Desktop" / f"{company.lower()}.db"

    with sqlite3.connect(DB) as con:
        con.execute("ATTACH DATABASE ? AS new_db", (str(new_db),))

        con.execute(
            """
            CREATE TABLE new_db.jobs AS
            SELECT *
            FROM main.jobs
            WHERE company_name = ?
        """,
            (company,),
        )

        con.execute("DETACH DATABASE new_db")

    DB.unlink()
    new_db.replace(DB)


def main():
    print(" ")
    copy_db_with_kpmg()


if __name__ == "__main__":
    main()
