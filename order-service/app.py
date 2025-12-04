from datetime import datetime
from typing import Optional
import os
import httpx

from fastapi import FastAPI, HTTPException, Depends, status, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import enum

# Database configuration from environment variables
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'order_db'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'port': os.getenv('DB_PORT', '5432')
}

# External service URLs from environment variables
BILLING_APP_URL = os.getenv('BILLING_APP_URL', 'http://billing-service:8000')
NOTIFICATION_APP_URL = os.getenv('NOTIFICATION_APP_URL', 'http://notification-service:8000')

# Create database URL from config
DATABASE_URL = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"

# Create database engine
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Define order status enum
class OrderStatus(str, enum.Enum):
    NEW = "new"
    PAID = "paid"
    CANCELLED = "cancelled"

# FastAPI application
app = FastAPI(
    title="Order Service API",
    description="Service for managing orders with payment processing",
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
class Order(Base):
    """Order model"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    price = Column(Float, nullable=False)
    product_name = Column(String(255), nullable=False)
    status = Column(String(20), default=OrderStatus.NEW.value, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    user_id = Column(Integer, nullable=False, index=True)

# Pydantic schemas for requests
class OrderCreateRequest(BaseModel):
    """Schema for creating an order"""
    price: float = Field(..., gt=0, description="Order price must be greater than 0")
    product_name: str = Field(..., min_length=1, max_length=255, description="Product name (1-255 characters)")
    
    @validator('price')
    def validate_price(cls, v):
        if v <= 0:
            raise ValueError('price must be greater than 0')
        return round(v, 2)
    
    @validator('product_name')
    def validate_product_name(cls, v):
        if not v or not v.strip():
            raise ValueError('product_name cannot be empty')
        return v.strip()

# Pydantic schemas for responses
class OrderResponse(BaseModel):
    """Schema for order response"""
    id: int
    price: float
    product_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    user_id: int
    
    class Config:
        from_attributes = True

class OrderCreateResponse(BaseModel):
    """Response for order creation"""
    order_id: int
    price: float
    product_name: str
    status: str
    user_id: int
    message: str

# External service schemas
class BalanceResponse(BaseModel):
    """Schema for balance response from billing service"""
    user_id: int
    balance: float

class WithdrawRequest(BaseModel):
    """Schema for withdraw request to billing service"""
    amount: float

class NotificationRequest(BaseModel):
    """Schema for notification request"""
    recipient_id: int
    message: str

# Dependencies
def get_db():
    """Database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_id(x_authenticated_user_id: Optional[str] = Header(None)):
    """Get user ID from X-Authenticated-User-ID header"""
    if not x_authenticated_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Authenticated-User-ID header is required"
        )
    
    try:
        user_id = int(x_authenticated_user_id)
        if user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User ID must be greater than 0"
            )
        return user_id
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid User ID format. Must be an integer"
        )

# Helper functions
def create_order(price: float, product_name: str, user_id: int, db: Session) -> Order:
    """Create new order in database"""
    order = Order(
        price=price,
        product_name=product_name,
        status=OrderStatus.NEW.value,
        user_id=user_id
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order

def update_order_status(order_id: int, status: OrderStatus, db: Session) -> Order:
    """Update order status"""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError(f"Order with id {order_id} not found")
    
    order.status = status.value
    order.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(order)
    return order

async def get_user_balance(user_id: int) -> float:
    """Get user balance from billing service"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{BILLING_APP_URL}/api/v1/balance/{user_id}")
            response.raise_for_status()
            
            balance_data = BalanceResponse(**response.json())
            return balance_data.balance
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to connect to billing service: {str(e)}"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Billing service error: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user balance: {str(e)}"
        )

async def withdraw_funds(user_id: int, amount: float) -> bool:
    """Withdraw funds from user account via billing service"""
    try:
        withdraw_data = WithdrawRequest(amount=amount)
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{BILLING_APP_URL}/api/v1/withdraw/{user_id}",
                json=withdraw_data.dict()
            )
            
            # Check if response is successful (2xx status code)
            response.raise_for_status()
            
            # Funds successfully withdrawn
            return True
            
    except httpx.RequestError as e:
        # Log the error
        print(f"Failed to connect to billing service for withdrawal: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to process payment: billing service unavailable"
        )
    except httpx.HTTPStatusError as e:
        # Handle specific HTTP errors
        if e.response.status_code == 400:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient funds or invalid amount"
            )
        elif e.response.status_code == 404:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User not found in billing system"
            )
        else:
            print(f"Billing service returned error during withdrawal: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Payment processing failed: billing service error"
            )
    except Exception as e:
        # Log unexpected errors
        print(f"Unexpected error during withdrawal: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment processing failed: internal error"
        )

async def send_notification(recipient_id: int, message: str):
    """Send notification through notification service"""
    try:
        notification_data = NotificationRequest(
            recipient_id=recipient_id,
            message=message
        )
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{NOTIFICATION_APP_URL}/api/v1/notification/send",
                json=notification_data.dict()
            )
            
            # Check if response is successful (2xx status code)
            response.raise_for_status()
            
            # We don't need to process the response content, just ensure it's successful
            return True
            
    except httpx.RequestError as e:
        # Log the error but don't fail the order creation
        print(f"Failed to send notification: {str(e)}")
        return False
    except httpx.HTTPStatusError as e:
        # Log the error but don't fail the order creation
        print(f"Notification service returned error: {str(e)}")
        return False
    except Exception as e:
        # Log the error but don't fail the order creation
        print(f"Unexpected error sending notification: {str(e)}")
        return False

# API Endpoints
@app.post("/api/v1/order/create", 
          response_model=OrderCreateResponse,
          status_code=status.HTTP_201_CREATED)
async def create_order_endpoint(
    request: OrderCreateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_user_id)
):
    """
    Create a new order with payment processing
    
    - **price**: Order price (must be greater than 0)
    - **product_name**: Name of the product
    - **X-Authenticated-User-ID**: User ID from header
    """
    try:
        # Step 1: Create order with initial status 'new'
        order = create_order(
            price=request.price,
            product_name=request.product_name,
            user_id=user_id,
            db=db
        )
        
        # Step 2: Get user balance from billing service
        user_balance = await get_user_balance(user_id)
        
        # Step 3: Check if user has sufficient balance
        if request.price > user_balance:
            # Insufficient funds - cancel order
            order = update_order_status(order.id, OrderStatus.CANCELLED, db)
            
            # Send cancellation notification
            notification_message = f"Order {order.id} cancelled, insufficient funds"
            await send_notification(user_id, notification_message)
            
            return OrderCreateResponse(
                order_id=order.id,
                price=order.price,
                product_name=order.product_name,
                status=order.status,
                user_id=user_id,
                message="Order cancelled due to insufficient funds"
            )
        else:
            # Sufficient funds - process payment
            try:
                # Step 4: Withdraw funds from user account
                await withdraw_funds(user_id, request.price)
                
                # Step 5: Update order status to paid
                order = update_order_status(order.id, OrderStatus.PAID, db)
                
                # Step 6: Send payment confirmation notification
                notification_message = f"Order {order.id} paid successfully. Amount: ${order.price:.2f}"
                await send_notification(user_id, notification_message)
                
                return OrderCreateResponse(
                    order_id=order.id,
                    price=order.price,
                    product_name=order.product_name,
                    status=order.status,
                    user_id=user_id,
                    message=f"Order created and paid successfully. ${order.price:.2f} deducted from your account."
                )
                
            except HTTPException as e:
                # If withdrawal fails, mark order as cancelled
                order = update_order_status(order.id, OrderStatus.CANCELLED, db)
                
                # Send cancellation notification
                notification_message = f"Order {order.id} cancelled due to payment processing error"
                await send_notification(user_id, notification_message)
                
                raise HTTPException(
                    status_code=e.status_code,
                    detail=f"Order created but payment failed: {e.detail}"
                )
                
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Log error
        print(f"Error creating order: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create order: {str(e)}"
        )

@app.get("/api/v1/orders/{requested_user_id}", response_model=list[OrderResponse])
def get_user_orders(
    requested_user_id: int,
    db: Session = Depends(get_db),
    authenticated_user_id: int = Depends(get_user_id),
    skip: int = 0,
    limit: int = 100
):
    """
    Get all orders for a specific user
    
    - **requested_user_id**: User ID for which to retrieve orders
    - **X-Authenticated-User-ID**: User ID from header (must match requested_user_id)
    - **skip**: Number of records to skip (for pagination)
    - **limit**: Maximum number of records to return
    """
    # Check if requested user ID is valid
    if requested_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID must be greater than 0"
        )
    
    # Security check: ensure user can only access their own orders
    if requested_user_id != authenticated_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own orders"
        )
    
    try:
        # Get orders for the requested user
        orders = db.query(Order)\
            .filter(Order.user_id == requested_user_id)\
            .order_by(Order.created_at.desc())\
            .offset(skip)\
            .limit(limit)\
            .all()
        
        return orders
        
    except Exception as e:
        print(f"Error getting orders for user {requested_user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get orders: {str(e)}"
        )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Service health check"""
    health_status = {
        "status": "healthy",
        "service": "order",
        "timestamp": datetime.utcnow().isoformat(),
        "dependencies": {}
    }
    
    # Check database connection
    try:
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        health_status["dependencies"]["database"] = "healthy"
    except Exception as e:
        health_status["dependencies"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check billing service connection
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BILLING_APP_URL}/health")
            if response.status_code == 200:
                health_status["dependencies"]["billing_service"] = "healthy"
            else:
                health_status["dependencies"]["billing_service"] = f"unhealthy: HTTP {response.status_code}"
                health_status["status"] = "degraded"
    except Exception as e:
        health_status["dependencies"]["billing_service"] = f"unavailable: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check notification service connection
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NOTIFICATION_APP_URL}/health")
            if response.status_code == 200:
                health_status["dependencies"]["notification_service"] = "healthy"
            else:
                health_status["dependencies"]["notification_service"] = f"unhealthy: HTTP {response.status_code}"
                health_status["status"] = "degraded"
    except Exception as e:
        health_status["dependencies"]["notification_service"] = f"unavailable: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

# API info endpoint
@app.get("/")
def root():
    """API information"""
    return {
        "service": "Order Service",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "create_order": "POST /api/v1/order/create",
            "get_user_orders": "GET /api/v1/orders/{user_id}"
        },
        "config": {
            "billing_service_url": BILLING_APP_URL,
            "notification_service_url": NOTIFICATION_APP_URL
        }
    }