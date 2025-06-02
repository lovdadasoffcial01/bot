from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(String)
    role = Column(String)  # "user" or "assistant"
    type = Column(String)  # "text" or "image"
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_user = Column(Boolean, default=True)  # <-- Add this line

engine = create_engine("sqlite:///conversations.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
