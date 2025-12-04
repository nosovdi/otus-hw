from fastapi import FastAPI, HTTPException, Depends, status, Request, Response  # <-- ВСЕ импорты FastAPI здесь
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel
import os
from datetime import datetime, timedelta
import jwt  # Убедитесь, что у вас установлен PyJWT: pip install PyJWT
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional
import hashlib
from prometheus_client import generate_latest, REGISTRY, CONTENT_TYPE_LATEST  # <-- Добавить CONTENT_TYPE_LATEST

app = FastAPI(title="API Gateway", version="1.0.0")

# Настройки
API_PREFIX = "/api/v1"
YOUR_APP_URL = os.getenv("USER_APP_URL", "http://your-app:8000")
BILLING_APP_URL = os.getenv("BILLING_APP_URL", "http://billing-app:8000")
NOTIFICATION_APP_URL = os.getenv("NOTIFICATION_APP_URL", "http://notification-app:8000")
ORDER_APP_URL = os.getenv("ORDER_APP_URL", "http://order-app:8000")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# CORS настройки
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Безопасность
security = HTTPBearer()

# Модели данных
class UserCreate(BaseModel):
    username: str
    password: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserProfile(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user_id: int

# Настройки базы данных
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME', 'userdb'),
    'user': os.getenv('DB_USER', 'userdb'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'port': os.getenv('DB_PORT', '5432')
}

def get_db_connection():
    """Создание подключения к базе данных"""
    return psycopg2.connect(**DB_CONFIG)

def hash_password(password: str) -> str:
    """Хеширование пароля (в production используйте bcrypt или argon2)"""
    return hashlib.sha256(password.encode()).hexdigest()

def authenticate_user(username: str, password: str):
    """Аутентификация пользователя по логину и паролю"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute(
            'SELECT id, username, password_hash FROM users WHERE username = %s',
            (username,)
        )
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not user:
            return None
        
        # Проверяем пароль
        if user['password_hash'] == hash_password(password):
            return user
        return None
        
    except Exception as e:
        print(f"Error authenticating user: {e}")
        return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Создание JWT токена"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str):
    """Верификация JWT токена"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        
        if user_id is None:
            return None
        
        # Преобразуем user_id к int если это возможно
        if isinstance(user_id, str):
            try:
                user_id = int(user_id)
            except ValueError:
                # Если не получается преобразовать в int, оставляем как есть
                pass
        
        return {
            "user_id": user_id,
            "username": payload.get("username")
        }
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        return None
    except Exception as e:
        print(f"Error verifying token: {e}")
        return None
    
async def token_check(user_id, current_user, request, backend_url, method):
    """Общий метод проверки токена и проксирования запроса"""
    # Проверяем, что пользователь запрашивает свой собственный профиль
    if not await verify_user_access(current_user, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. You can only access your own"
        )
    
    # Получаем пользователя из БД для проверки существования
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Получаем тело запроса для POST, PUT, PATCH методов
    request_body = None
    if method in ["POST", "PUT", "PATCH"]:
        try:
            # Пытаемся получить JSON из запроса
            if hasattr(request, 'json'):
                request_body = await request.json()
            else:
                # Если request не имеет атрибута json, используем body
                body = await request.body()
                if body:
                    import json
                    request_body = json.loads(body)
        except Exception as e:
            # Если нет тела или невалидный JSON, продолжаем без него
            print(f"Warning: Could not parse request body: {e}")
            request_body = None
    
    # Проксируем запрос к вашему приложению
    async with httpx.AsyncClient() as client:
        try:
            # Получаем токен из заголовка
            auth_header = request.headers.get("authorization") if request else None
            
            # Формируем заголовки для передачи
            headers = {"X-Authenticated-User-ID": str(current_user["user_id"])}
            if auth_header:
                headers["Authorization"] = auth_header
            
            # Также копируем Content-Type если есть
            content_type = request.headers.get("content-type")
            if content_type:
                headers["Content-Type"] = content_type
            
            # Выполняем запрос в зависимости от метода
            match method:
                case "GET":
                    response = await client.get(
                        backend_url,
                        headers=headers,
                        timeout=10.0
                    )
                case "POST":
                    response = await client.post(
                        backend_url,
                        json=request_body,
                        headers=headers,
                        timeout=10.0
                    )
                case "PUT":
                    response = await client.put(
                        backend_url,
                        json=request_body,
                        headers=headers,
                        timeout=10.0
                    )
                case "PATCH":
                    response = await client.patch(
                        backend_url,
                        json=request_body,
                        headers=headers,
                        timeout=10.0
                    )
                case "DELETE":
                    # Для DELETE тоже можно передавать тело
                    if request_body:
                        response = await client.delete(
                            backend_url,
                            json=request_body,
                            headers=headers,
                            timeout=10.0
                        )
                    else:
                        response = await client.delete(
                            backend_url,
                            headers=headers,
                            timeout=10.0
                        )
                case _:
                    raise HTTPException(
                        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
                        detail=f"Method {method} not allowed"
                    )
            
            # Проверяем статус ответа
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text if response.text else f"Error: {response.status_code}"
                )
            
            # Возвращаем ответ
            if response.status_code == 204:
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            
            # Пытаемся вернуть JSON, если это возможно
            try:
                return response.json()
            except:
                return Response(
                    content=response.content,
                    media_type=response.headers.get("content-type", "application/json"),
                    status_code=response.status_code
                )
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Backend service timeout"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Backend service unavailable: {str(e)}"
            )

async def verify_user_access(token_data: dict, requested_user_id: int):
    """Проверяет, что пользователь имеет доступ к запрашиваемым данным"""
    # Сравниваем как строки для надежности
    token_user_id = str(token_data.get("user_id", ""))
    requested_id = str(requested_user_id)
    return token_user_id == requested_id

# Dependency для аутентификации
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Получение текущего пользователя из токена"""
    token = credentials.credentials
    user_data = verify_token(token)
    
    if user_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_data

def get_user_by_id(user_id: int):
    """Получение пользователя по ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute(
            'SELECT id, username, firstName, lastName, email, phone FROM users WHERE id = %s',
            (user_id,)
        )
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return user
    except Exception as e:
        print(f"Error getting user by id: {e}")
        return None

# Эндпоинты API Gateway
@app.post(f"{API_PREFIX}/register", response_model=Token)
async def register(user_data: UserCreate):
    """Регистрация нового пользователя"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Проверяем существование пользователя
        cursor.execute(
            'SELECT * FROM users WHERE username = %s', 
            (user_data.username,)
        )
        existing_user = cursor.fetchone()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists"
            )
        
        # Создаем пользователя с хэшированным паролем
        cursor.execute(
            '''INSERT INTO users (username, firstName, lastName, email, phone, password_hash)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, username''',
            (user_data.username, user_data.firstName, user_data.lastName,
             user_data.email, user_data.phone, hash_password(user_data.password))
        )

        user = cursor.fetchone()

        # Создаем запись в биллинге
        cursor.execute(
            '''INSERT INTO billing (id, balance)
               VALUES (%s, 0)''',
            (user['id'],)
        )
        
        conn.commit()
        
        # Создаем токен с user_id как int
        access_token = create_access_token(
            data={"sub": user['id'], "username": user['username']}
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user['id']
        }
        
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )
    finally:
        if conn:
            conn.close()

@app.post(f"{API_PREFIX}/login", response_model=Token)
async def login(user_data: UserLogin):
    """Аутентификация пользователя"""
    user = authenticate_user(user_data.username, user_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Создаем токен с user_id как int
    access_token = create_access_token(
        data={"sub": user['id'], "username": user['username']}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user['id']
    }

@app.get(f"{API_PREFIX}/user/{{user_id}}")
async def get_user_profile(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Получение профиля пользователя (с проверкой прав доступа)"""
    # Проверяем, что пользователь запрашивает свой собственный профиль
    if not await verify_user_access(current_user, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied. You can only access your own profile"
        )
    
    # Получаем пользователя из БД для проверки существования
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Проксируем запрос к вашему приложению
    async with httpx.AsyncClient() as client:
        try:
            # Получаем токен из заголовка
            auth_header = request.headers.get("authorization") if request else None
            
            # Формируем заголовки для передачи
            headers = {"X-Authenticated-User-ID": str(current_user["user_id"])}
            if auth_header:
                headers["Authorization"] = auth_header
            
            response = await client.get(
                f"{YOUR_APP_URL}{API_PREFIX}/user/{user_id}",
                headers=headers,
                timeout=10.0
            )
            
            # Проверяем статус ответа
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )
            
            return response.json()
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Backend service timeout"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Backend service unavailable: {str(e)}"
            )

@app.put(f"{API_PREFIX}/user/{{user_id}}")
async def update_user_profile(
    user_id: int, 
    profile_data: UserProfile,
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Обновление профиля пользователя (с проверкой прав доступа)"""
    # Проверяем, что пользователь обновляет свой собственный профиль
    if not await verify_user_access(current_user, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only update your own profile"
        )
    
    # Проверяем существование пользователя
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Проксируем запрос к вашему приложению
    async with httpx.AsyncClient() as client:
        try:
            # Получаем токен из заголовка
            auth_header = request.headers.get("authorization") if request else None
            
            # Формируем заголовки для передачи
            headers = {
                "Content-Type": "application/json",
                "X-Authenticated-User-ID": str(current_user["user_id"])
            }
            if auth_header:
                headers["Authorization"] = auth_header
            
            # Подготавливаем данные для обновления
            update_data = profile_data.dict(exclude_unset=True)
            
            response = await client.put(
                f"{YOUR_APP_URL}{API_PREFIX}/user/{user_id}",
                json=update_data,
                headers=headers,
                timeout=10.0
            )
            
            # Проверяем статус ответа
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )
            
            return response.json()
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Backend service timeout"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Backend service unavailable: {str(e)}"
            )

# УДАЛИТЬ эту строку: from fastapi import FastAPI, HTTPException, Depends, status, Request, Response  # <-- Удалить дублирующий импорт

@app.delete(f"{API_PREFIX}/user/{{user_id}}")
async def delete_user_profile(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Удаление профиля пользователя (с проверкой прав доступа)"""
    # Проверяем, что пользователь удаляет свой собственный профиль
    if not await verify_user_access(current_user, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. You can only delete your own profile"
        )
    
    # Проверяем существование пользователя
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Проксируем запрос к вашему приложению
    async with httpx.AsyncClient() as client:
        try:
            # Получаем токен из заголовка
            auth_header = request.headers.get("authorization") if request else None
            
            # Формируем заголовки для передачи
            headers = {
                "X-Authenticated-User-ID": str(current_user["user_id"])
            }
            if auth_header:
                headers["Authorization"] = auth_header
            
            response = await client.delete(
                f"{YOUR_APP_URL}{API_PREFIX}/user/{user_id}",
                headers=headers,
                timeout=10.0
            )
            
            # Проверяем статус ответа
            if response.status_code == 204:
                # Возвращаем успешный ответ без тела
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            else:
                # Пробрасываем ошибку от бэкенда
                try:
                    error_data = response.json()
                    detail = error_data.get('message', response.text)
                except:
                    detail = response.text
                    
                raise HTTPException(
                    status_code=response.status_code,
                    detail=detail
                )
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Backend service timeout"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Backend service unavailable: {str(e)}"
            )

@app.get(f"{API_PREFIX}/me")
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """Получение профиля текущего пользователя"""
    user_id = current_user["user_id"]
    
    # Получаем профиль пользователя
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {
        "id": user["id"],
        "username": user["username"],
        "firstName": user["firstname"],
        "lastName": user["lastname"],
        "email": user["email"],
        "phone": user["phone"]
    }

@app.get(f"{API_PREFIX}/verify-token")
async def verify_token_endpoint(current_user: dict = Depends(get_current_user)):
    """Эндпоинт для проверки токена и получения информации о пользователе"""
    return {
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "is_authenticated": True
    }

@app.get("/health/")
async def health_check():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{YOUR_APP_URL}/health/")
            return response.json()
        except httpx.RequestError:
            raise HTTPException(status_code=500, detail="Backend service unavailable")

@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )

#----------------------------------------------------       
# Проксирование на сервис Billing
#----------------------------------------------------
@app.post(f"{API_PREFIX}/deposit/{{user_id}}")
async def deposit(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    return await token_check(user_id,current_user,request,f"{BILLING_APP_URL}{API_PREFIX}/deposit/{user_id}","POST")

@app.post(f"{API_PREFIX}/withdraw/{{user_id}}")
async def deposit(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    return await token_check(user_id,current_user,request,f"{BILLING_APP_URL}{API_PREFIX}/withdraw/{user_id}","POST")

@app.get(f"{API_PREFIX}/balance/{{user_id}}")
async def deposit(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    return await token_check(user_id,current_user,request,f"{BILLING_APP_URL}{API_PREFIX}/balance/{user_id}","GET")


#----------------------------------------------------       
# Проксирование на сервис Notification
#----------------------------------------------------

@app.post(f"{API_PREFIX}/notification/send")
async def send_notification(request: Request):
    # Build target service URL
    target_url = f"{NOTIFICATION_APP_URL}{API_PREFIX}/notification/send"
    request_data = await request.body()
    
    # Get headers from request
    headers = dict(request.headers)
    
    # Remove host to avoid conflict
    if 'host' in headers:
        del headers['host']
    
    # Make request to target service
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url=target_url,
            content=request_data,
            headers=headers
        )
    
    # Return response from target service
    return JSONResponse(
        content=response.json(),
        status_code=response.status_code
    )

@app.get(f"{API_PREFIX}/notification/{{user_id}}")
async def notification(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    return await token_check(user_id,current_user,request,f"{NOTIFICATION_APP_URL}{API_PREFIX}/notification/{user_id}","GET")


#----------------------------------------------------       
# Проксирование на сервис Order
#----------------------------------------------------

@app.post(f"{API_PREFIX}/order/create")
async def deposit(
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    backend_url = f"{ORDER_APP_URL}{API_PREFIX}/order/create"
    current_user_id = current_user["user_id"]
    try:
        # Пытаемся получить JSON из запроса
        if hasattr(request, 'json'):
            request_body = await request.json()
        else:
            # Если request не имеет атрибута json, используем body
            body = await request.body()
            if body:
                import json
                request_body = json.loads(body)
    except Exception as e:
        # Если нет тела или невалидный JSON, продолжаем без него
        print(f"Warning: Could not parse request body: {e}")
        request_body = None
    
    # Проксируем запрос к вашему приложению
    async with httpx.AsyncClient() as client:
        try:
            # Получаем токен из заголовка
            auth_header = request.headers.get("authorization") if request else None
            
            # Формируем заголовки для передачи
            headers = {"X-Authenticated-User-ID": str(current_user["user_id"])}
            if auth_header:
                headers["Authorization"] = auth_header
            
            # Также копируем Content-Type если есть
            content_type = request.headers.get("content-type")
            if content_type:
                headers["Content-Type"] = content_type
            
            response = await client.post(
                        backend_url,
                        json=request_body,
                        headers=headers,
                        timeout=10.0
                    )
            
            # Проверяем статус ответа
            if response.status_code >= 400:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text if response.text else f"Error: {response.status_code}"
                )
            
            # Возвращаем ответ
            if response.status_code == 204:
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            
            # Пытаемся вернуть JSON, если это возможно
            try:
                return response.json()
            except:
                return Response(
                    content=response.content,
                    media_type=response.headers.get("content-type", "application/json"),
                    status_code=response.status_code
                )
            
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Backend service timeout"
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Backend service unavailable: {str(e)}"
            )

@app.get(f"{API_PREFIX}/orders/{{user_id}}")
async def notification(
    user_id: int, 
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    return await token_check(user_id,current_user,request,f"{ORDER_APP_URL}{API_PREFIX}/orders/{user_id}","GET")