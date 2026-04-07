from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional

class ContactSubmission(BaseModel):
    """Model for contact form submissions stored in MongoDB"""
    name: str
    email: EmailStr
    subject: str
    message: str
    phone: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "new"  # new, read, replied
    
class ContactSubmissionCreate(BaseModel):
    """Model for creating new contact submissions"""
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    subject: str = Field(..., min_length=5, max_length=200)
    message: str = Field(..., min_length=10, max_length=5000)
    phone: Optional[str] = Field(None, max_length=20)

class ContactResponse(BaseModel):
    """Response model for contact form submission"""
    status: str
    message: str
    submission_id: Optional[str] = None
