import os
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).with_name(".env"))

with MongoClient(
    os.environ["MONGODB_URI"],
    serverSelectionTimeoutMS=10000,
) as client:
    client.admin.command("ping")
    db = client[os.environ["MONGODB_DB"]]
    count = db["sessions"].count_documents({})
    print("Connected to MongoDB Atlas!")
    print(f"Sessions in database: {count}")