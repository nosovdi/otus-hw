# main.py
from datetime import datetime
from typing import List
import os

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'notification_db'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'port': os.getenv('DB_PORT', '5432')
}

# Create database URL from config
DATABASE_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"

# Create database engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# FastAPI application
app = FastAPI(
    title="Notification Service API",
    description="Service for sending and receiving notifications",
    version="1.0.0"
)

# CORS settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database models
class Notification(Base):
    """Notification model"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    recipient_id = Column(Integer, nullable=False, index=True)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic schemas
class NotificationSendRequest(BaseModel):
    """Schema for sending notification"""
    recipient_id: int = Field(..., gt=0, description="Recipient ID must be greater than 0")
    message: str = Field(..., min_length=1, max_length=1000, description="Message text (1-1000 characters)")
    
    @validator('recipient_id')
    def validate_recipient_id(cls, v):
        if v <= 0:
            raise ValueError('recipient_id must be greater than 0')
        return v
    
    @validator('message')
    def validate_message(cls, v):
        if not v or not v.strip():
            raise ValueError('message cannot be empty')
        return v.strip()

class NotificationSendResponse(BaseModel):
    """Response for send notification"""
    notification_id: int
    recipient_id: int
    message: str
    created_at: datetime
    status: str = "sent"

class NotificationResponse(BaseModel):
    """Schema for notification response"""
    id: int
    recipient_id: int
    message: str
    created_at: datetime
    is_read: bool
    
    class Config:
        from_attributes = True

class NotificationsListResponse(BaseModel):
    """Response for notifications list"""
    user_id: int
    total_count: int
    unread_count: int
    notifications: List[NotificationResponse]

# Dependencies
def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper functions
def create_notification(recipient_id: int, message: str, db: Session):
    """Create new notification in database"""
    notification = Notification(
        recipient_id=recipient_id,
        message=message
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification

def get_user_notifications(user_id: int, db: Session):
    """Get last 100 notifications for specific user"""
    # Get last 100 notifications
    notifications = db.query(Notification)\
        .filter(Notification.recipient_id == user_id)\
        .order_by(Notification.created_at.desc())\
        .limit(100)\
        .all()
    
    # Get total count
    total_count = db.query(Notification)\
        .filter(Notification.recipient_id == user_id)\
        .count()
    
    # Get unread count
    unread_count = db.query(Notification)\
        .filter(Notification.recipient_id == user_id, Notification.is_read == False)\
        .count()
    
    return notifications, total_count, unread_count

# API Endpoints
@app.post("/api/v1/notification/send", 
          response_model=NotificationSendResponse,
          status_code=status.HTTP_201_CREATED)
def send_notification(
    request: NotificationSendRequest,
    db: Session = Depends(get_db)
):
    """
    Send notification to user
    
    - **recipient_id**: User ID of the recipient
    - **message**: Notification message text
    """
    try:
        # Create notification in DB
        notification = create_notification(
            recipient_id=request.recipient_id,
            message=request.message,
            db=db
        )
        
        # Here you can add integration with real notification services:
        # - Email
        # - SMS
        # - Push notifications
        # - WebSocket
        # - etc.
        
        return NotificationSendResponse(
            notification_id=notification.id,
            recipient_id=notification.recipient_id,
            message=notification.message,
            created_at=notification.created_at
        )
        
    except Exception as e:
        # Log error
        print(f"Error sending notification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send notification: {str(e)}"
        )

@app.get("/api/v1/notification/{user_id}", response_model=NotificationsListResponse)
def get_notifications(
    user_id: int,
    db: Session = Depends(get_db)
):
    """
    Get notifications for user
    
    - **user_id**: User ID
    - Returns last 100 notifications
    """
    if user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id must be greater than 0"
        )
    
    try:
        # Get notifications
        notifications, total_count, unread_count = get_user_notifications(
            user_id=user_id,
            db=db
        )
        
        return NotificationsListResponse(
            user_id=user_id,
            total_count=total_count,
            unread_count=unread_count,
            notifications=notifications
        )
        
    except Exception as e:
        print(f"Error getting notifications: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get notifications: {str(e)}"
        )

# Health check endpoint
@app.get("/health")
def health_check():
    """Service health check"""
    return {
        "status": "healthy", 
        "service": "notification",
        "timestamp": datetime.utcnow()
    }

# API info endpoint
@app.get("/")
def root():
    """API information"""
    return {
        "service": "Notification Service",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "send_notification": "POST /api/v1/notification/send",
            "get_notifications": "GET /api/v1/notification/{user_id}"
        }
    }