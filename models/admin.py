from pydantic import BaseModel
from typing import Optional

class AdminLogin(BaseModel):
    """Admin login credentials"""
    username: str
    password: str

class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"

class UpdateSubmissionStatus(BaseModel):
    """Update submission status"""
    status: str  # new, read, replied
