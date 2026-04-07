from fastapi import FastAPI, APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
import uuid
from datetime import datetime, timezone
from models.contact import ContactSubmissionCreate, ContactResponse
from models.admin import AdminLogin, Token, UpdateSubmissionStatus
from services.email_service import email_service
from services.auth_service import authenticate_admin, create_access_token, verify_token


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()

# Dependency for protected routes
async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token for admin routes"""
    token = credentials.credentials
    payload = verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    return payload


# Define Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Ignore MongoDB's _id field
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "Hello World"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)
    
    # Convert to dict and serialize datetime to ISO string for MongoDB
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    
    _ = await db.status_checks.insert_one(doc)
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    # Exclude MongoDB's _id field from the query results
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    
    # Convert ISO string timestamps back to datetime objects
    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])
    
    return status_checks

@api_router.post("/contact", response_model=ContactResponse)
async def submit_contact_form(contact: ContactSubmissionCreate):
    """
    Submit contact form and send email notifications
    
    Stores submission in MongoDB and sends emails to:
    - Admin: notification with full submission details
    - User: confirmation email
    """
    try:
        logger.info(f"Processing contact form from {contact.email}")
        
        # Prepare contact data for database
        contact_dict = contact.model_dump()
        contact_dict['created_at'] = datetime.now(timezone.utc).isoformat()
        contact_dict['status'] = 'new'
        contact_dict['id'] = str(uuid.uuid4())
        
        # Save to MongoDB
        await db.contact_submissions.insert_one(contact_dict)
        logger.info(f"Contact submission saved to database: {contact_dict['id']}")
        
        # Send email notifications
        email_result = email_service.send_contact_notification(contact.model_dump())
        
        if email_result['status'] == 'error':
            logger.warning(f"Email sending failed but submission saved: {email_result['message']}")
            # Still return success since data is saved
            return ContactResponse(
                status="success",
                message="Your message has been received. We'll get back to you soon!",
                submission_id=contact_dict['id']
            )
        
        logger.info(f"Contact form processed successfully for {contact.email}")
        
        return ContactResponse(
            status="success",
            message="Your message has been sent successfully. Check your email for confirmation!",
            submission_id=contact_dict['id']
        )
        
    except Exception as e:
        logger.error(f"Error processing contact form: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process contact form. Please try again later."
        )

@api_router.post("/admin/login", response_model=Token)
async def admin_login(credentials: AdminLogin):
    """Admin login endpoint"""
    if not authenticate_admin(credentials.username, credentials.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
    
    access_token = create_access_token(data={"sub": credentials.username, "role": "admin"})
    
    return Token(access_token=access_token)

@api_router.get("/admin/submissions")
async def get_all_submissions(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    payload: dict = Depends(verify_admin_token)
):
    """
    Get contact form submissions with pagination (protected route)
    
    Args:
        status_filter: Filter by status (new, read, replied)
        skip: Number of records to skip for pagination
        limit: Maximum number of records to return (max 100)
    """
    try:
        # Validate and limit the page size
        limit = min(limit, 100)
        
        query = {}
        if status_filter and status_filter in ["new", "read", "replied"]:
            query["status"] = status_filter
        
        # Fetch only necessary fields for list view
        submissions = await db.contact_submissions.find(
            query,
            {
                "_id": 0,
                "id": 1,
                "name": 1,
                "email": 1,
                "phone": 1,
                "subject": 1,
                "message": 1,
                "status": 1,
                "created_at": 1
            }
        ).sort("created_at", -1).skip(skip).to_list(limit)
        
        # Get total count for pagination
        total_count = await db.contact_submissions.count_documents(query)
        
        return {
            "status": "success",
            "count": len(submissions),
            "total": total_count,
            "skip": skip,
            "limit": limit,
            "submissions": submissions
        }
    except Exception as e:
        logger.error(f"Error fetching submissions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch submissions"
        )

@api_router.patch("/admin/submissions/{submission_id}")
async def update_submission_status(
    submission_id: str,
    update_data: UpdateSubmissionStatus,
    payload: dict = Depends(verify_admin_token)
):
    """Update submission status (protected route)"""
    try:
        if update_data.status not in ["new", "read", "replied"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid status. Must be 'new', 'read', or 'replied'"
            )
        
        result = await db.contact_submissions.update_one(
            {"id": submission_id},
            {"$set": {"status": update_data.status}}
        )
        
        if result.matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found"
            )
        
        return {
            "status": "success",
            "message": "Status updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating submission: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update submission"
        )

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()