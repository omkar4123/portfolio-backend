from fastapi import FastAPI, APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware   # ✅ FIXED IMPORT
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


# Load env
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL')
db_name = os.environ.get('DB_NAME', 'test')

client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# FastAPI app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# ✅ CORS FIX (VERY IMPORTANT)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all (fixes your issue instantly)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()


# 🔐 Verify admin token
async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    return payload


# Models
class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


# Routes
@api_router.get("/")
async def root():
    return {"message": "Hello World 🚀"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.model_dump())

    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()

    await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    data = await db.status_checks.find({}, {"_id": 0}).to_list(1000)

    for item in data:
        if isinstance(item['timestamp'], str):
            item['timestamp'] = datetime.fromisoformat(item['timestamp'])

    return data


@api_router.post("/contact", response_model=ContactResponse)
async def submit_contact_form(contact: ContactSubmissionCreate):
    try:
        contact_dict = contact.model_dump()
        contact_dict['created_at'] = datetime.now(timezone.utc).isoformat()
        contact_dict['status'] = 'new'
        contact_dict['id'] = str(uuid.uuid4())

        await db.contact_submissions.insert_one(contact_dict)

        email_result = email_service.send_contact_notification(contact.model_dump())

        return ContactResponse(
            status="success",
            message="Message received successfully!",
            submission_id=contact_dict['id']
        )

    except Exception as e:
        logger.error(str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@api_router.post("/admin/login", response_model=Token)
async def admin_login(credentials: AdminLogin):
    if not authenticate_admin(credentials.username, credentials.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": credentials.username})
    return Token(access_token=token)


@api_router.get("/admin/submissions")
async def get_submissions(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    payload: dict = Depends(verify_admin_token)
):
    query = {}
    if status_filter:
        query["status"] = status_filter

    data = await db.contact_submissions.find(query, {"_id": 0}).to_list(limit)
    total = await db.contact_submissions.count_documents(query)

    return {
        "count": len(data),
        "total": total,
        "data": data
    }


@api_router.patch("/admin/submissions/{submission_id}")
async def update_submission_status(
    submission_id: str,
    update_data: UpdateSubmissionStatus,
    payload: dict = Depends(verify_admin_token)
):
    result = await db.contact_submissions.update_one(
        {"id": submission_id},
        {"$set": {"status": update_data.status}}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")

    return {"message": "Updated"}


# Include router
app.include_router(api_router)


# Shutdown
@app.on_event("shutdown")
async def shutdown_db():
    client.close()


# 🚀 IMPORTANT
import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
