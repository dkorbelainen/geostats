#!/usr/bin/env python3
"""Quick script to set avatar for an account."""
import sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os

load_dotenv()

db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("DATABASE_URL not set. Create .env file with DATABASE_URL")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent / "src"))

from geostats.models import Account

engine = create_engine(db_url)

account_id = "61b24b1554e5b6000108c190"
avatar_url = "/static/avatars/shybtfly.png"

with Session(engine) as db:
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        print(f"Account {account_id} not found")
        sys.exit(1)

    account.avatar_url = avatar_url
    db.commit()
    print(f"Set avatar for {account.nick} to {avatar_url}")
