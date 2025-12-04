from datetime import datetime
from typing import Optional
from decimal import Decimal
import os

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'billing_db'),
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
    title="Billing Service API",
    description="Simple billing service for managing user accounts",
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
class User(Base):
    """User account model"""
    __tablename__ = "billing"  # Изменено с "users" на "billing"
    
    id = Column(Integer, primary_key=True, index=True)
    balance = Column(Numeric(10, 2), default=0.00, nullable=False)

# Create tables (auto-creates account on first operation)
Base.metadata.create_all(bind=engine)

# Pydantic schemas
class BalanceOperation(BaseModel):
    amount: Decimal = Field(gt=0, description="Amount must be greater than 0")
    
    @validator('amount')
    def validate_amount(cls, v):
        if v <= 0:
            raise ValueError('Amount must be greater than 0')
        return v

class DepositRequest(BalanceOperation):
    pass

class WithdrawRequest(BalanceOperation):
    pass

class BalanceResponse(BaseModel):
    user_id: int
    balance: Decimal

class OperationResponse(BaseModel):
    user_id: int
    operation: str
    amount: Decimal
    new_balance: Decimal

# Helper function to get or create user account
def get_or_create_user_account(user_id: int, db: Session):
    """Get existing user or create new account with zero balance"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        # Create account if doesn't exist
        user = User(id=user_id, balance=0.00)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

# Dependencies
def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# API Endpoints
@app.post("/api/v1/deposit/{user_id}", response_model=OperationResponse)
def deposit_to_account(
    user_id: int,
    deposit_request: DepositRequest,
    db: Session = Depends(get_db)
):
    """
    Deposit money to user account
    Creates account if doesn't exist
    """
    # Get or create user account
    user = get_or_create_user_account(user_id, db)
    
    # Update balance
    user.balance += deposit_request.amount
    
    db.commit()
    db.refresh(user)
    
    return OperationResponse(
        user_id=user_id,
        operation="deposit",
        amount=deposit_request.amount,
        new_balance=user.balance
    )

@app.post("/api/v1/withdraw/{user_id}", response_model=OperationResponse)
def withdraw_from_account(
    user_id: int,
    withdraw_request: WithdrawRequest,
    db: Session = Depends(get_db)
):
    """
    Withdraw money from user account
    """
    # Get user account
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )
    
    # Check sufficient funds
    if user.balance < withdraw_request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient funds"
        )
    
    # Update balance
    user.balance -= withdraw_request.amount
    
    db.commit()
    db.refresh(user)
    
    return OperationResponse(
        user_id=user_id,
        operation="withdraw",
        amount=withdraw_request.amount,
        new_balance=user.balance
    )

@app.get("/api/v1/balance/{user_id}", response_model=BalanceResponse)
def get_balance(user_id: int, db: Session = Depends(get_db)):
    """
    Get current user balance
    Creates account if doesn't exist
    """
    # Get or create user account
    user = get_or_create_user_account(user_id, db)
    
    return BalanceResponse(
        user_id=user.id,
        balance=user.balance
    )

# Health check endpoint
@app.get("/health")
def health_check():
    """Service health check"""
    return {"status": "healthy", "timestamp": datetime.utcnow()}

# API info endpoint
@app.get("/")
def root():
    """API information"""
    return {
        "service": "Billing Service",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "deposit": "POST /api/v1/deposit/{user_id}",
            "withdraw": "POST /api/v1/withdraw/{user_id}",
            "get_balance": "GET /api/v1/balance/{user_id}"
        }
    }
