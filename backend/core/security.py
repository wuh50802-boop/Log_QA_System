from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.config import settings

# ============================================
# 密码加密配置
# ============================================
# 使用 bcrypt 算法加密密码
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码是否正确
    
    Args:
        plain_password: 用户输入的明文密码
        hashed_password: 数据库中存储的哈希密码
    
    Returns:
        bool: 密码是否匹配
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    对密码进行哈希加密
    
    Args:
        password: 明文密码
    
    Returns:
        str: bcrypt 加密后的哈希值
    """
    return pwd_context.hash(password)


# ============================================
# JWT Token 配置
# ============================================

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    生成 JWT 访问令牌
    
    Args:
        data: 要编码到 Token 中的数据（如 {"sub": "username"}）
        expires_delta: 过期时间增量（默认使用配置中的值）
    
    Returns:
        str: JWT Token 字符串
    """
    to_encode = data.copy()
    
    # 设置过期时间
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    # 生成 Token
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.SECRET_KEY, 
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """
    解码 JWT Token
    
    Args:
        token: JWT Token 字符串
    
    Returns:
        Optional[dict]: 解码后的数据，验证失败返回 None
    """
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def get_username_from_token(token: str) -> Optional[str]:
    """
    从 Token 中提取用户名
    
    Args:
        token: JWT Token 字符串
    
    Returns:
        Optional[str]: 用户名，验证失败返回 None
    """
    payload = decode_token(token)
    if payload:
        return payload.get("sub")
    return None


def create_task_token(user_id: int, username: str, task_id: str,
                      expires_days: int = 7) -> str:
    """
    生成入库任务专用的长期 token。

    用于任务进度轮询，不受登录 token 30 分钟过期限制。
    payload 中带 scope=task + task_id，仅能访问 /api/ingest/tasks/{task_id}。

    Args:
        user_id: 用户 ID
        username: 用户名
        task_id: 关联的任务 ID
        expires_days: 有效期天数（默认 7 天）

    Returns:
        str: JWT Token 字符串
    """
    to_encode = {
        "sub": username,
        "uid": user_id,
        "scope": "task",
        "task_id": task_id,
    }
    expire = datetime.utcnow() + timedelta(days=expires_days)
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def decode_task_token(token: str, task_id: str) -> Optional[dict]:
    """
    解码并校验任务 token。

    Args:
        token: JWT Token 字符串
        task_id: 期望的任务 ID（用于校验 token 是否属于该任务）

    Returns:
        Optional[dict]: 解码后的 payload，校验失败返回 None
    """
    payload = decode_token(token)
    if not payload:
        return None
    # 必须是 task scope
    if payload.get("scope") != "task":
        return None
    # task_id 必须匹配
    if payload.get("task_id") != task_id:
        return None
    return payload