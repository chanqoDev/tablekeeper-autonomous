#!/usr/bin/env python3
"""Seed demo restaurants on first boot, then start the unchanged Stage 4 app."""
import json
import os
import sqlite3
import sys


DB_PATH = os.environ.get("TABLEKEEPER_DB", "/tmp/tablekeeper.sqlite3")
APP_PATH = "/app/app.py"
FIXTURE_PATH = "/app/demo-restaurants.json"


def seed_if_empty(db_path=DB_PATH, fixture_path=FIXTURE_PATH):
    with open(fixture_path, encoding="utf-8") as fixture_file:
        restaurants = json.load(fixture_file)
    if not isinstance(restaurants, list) or not restaurants:
        raise ValueError("demo restaurant fixture must be a non-empty list")
    ids = [r.get("id") for r in restaurants if isinstance(r, dict)]
    if len(ids) != len(restaurants) or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("demo restaurant ids must be unique strings")

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    db = sqlite3.connect(db_path, isolation_level=None)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""
            CREATE TABLE IF NOT EXISTS state (
                id INTEGER PRIMARY KEY CHECK(id=1),
                payload TEXT NOT NULL
            )
        """)
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT OR IGNORE INTO state VALUES (1, ?)",
            ('{"users":[],"restaurants":[],"reservations":[],"tokens":{},"receipts":[]}',),
        )
        row = db.execute("SELECT payload FROM state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("state row is missing")
        state = json.loads(row[0])
        if not isinstance(state, dict):
            raise ValueError("stored state must be a JSON object")
        existing = state.get("restaurants", [])
        if not isinstance(existing, list):
            raise ValueError("stored restaurants must be a list")
        if not existing:
            state["restaurants"] = restaurants
            db.execute(
                "UPDATE state SET payload=? WHERE id=1",
                (json.dumps(state, separators=(",", ":")),),
            )
        db.execute("COMMIT")
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def main():
    seed_if_empty()
    os.execv(sys.executable, [sys.executable, "-u", APP_PATH])


if __name__ == "__main__":
    main()
