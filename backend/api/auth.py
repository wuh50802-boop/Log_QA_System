#编写认证 API 路由
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime
import json

from core.database import get_db
from core.security import (
    verify_password, 
    get_password_hash, 
    create_access_token,
    decode_token,
    get_username_from_token
)
from models.user import User, UserRole
from models.audit_log import AuditLog
from schemas.auth import (
    LoginRequest, 
    RegisterRequest, 
    TokenResponse, 
    UserResponse
)

# 创建路由
router = APIRouter()
security = HTTPBearer()


# ============================================
# 辅助函数
# ============================================

def log_audit(db: Session, user_id: int, username: str, action: str, 
              resource: str = None, details: dict = None, ip: str = None):
    """
    记录审计日志
    """
    audit = AuditLog(
        user_id=user_id,
        username=username,
        action=action,
        resource=resource,
        details=json.dumps(details, ensure_ascii=False) if details else None,
        ip_address=ip,
    )
    db.add(audit)
    db.commit()


def get_current_user(db: Session = Depends(get_db), 
                     credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    依赖注入：从请求头中提取 Token，验证并返回当前用户
    
    用法：在需要登录的接口中添加 user = Depends(get_current_user)
    """
    token = credentials.credentials
    username = get_username_from_token(token)
    
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 从数据库查询用户
    user = db.query(User).filter(User.username == username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


# ============================================
# API 接口
# ============================================

@router.post("/register", response_model=UserResponse, summary="用户注册")
async def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    注册新用户
    
    - **username**: 用户名（3-50字符，唯一）
    - **password**: 密码（6-50字符）
    - **role**: 用户角色（admin/user，默认user）
    """
    # 1. 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == request.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 2. 哈希密码
    hashed_password = get_password_hash(request.password)
    
    # 3. 创建用户
    role = UserRole.ADMIN if request.role == "admin" else UserRole.USER
    new_user = User(
        username=request.username,
        password_hash=hashed_password,
        role=role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 4. 记录审计日志
    log_audit(
        db=db,
        user_id=new_user.id,
        username=new_user.username,
        action="register",
        resource="users",
        details={"role": new_user.role.value}
    )
    
    # 5. 返回用户信息
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        role=new_user.role.value,
        created_at=new_user.created_at.isoformat() if new_user.created_at else ""
    )


@router.post("/login", response_model=TokenResponse, summary="用户登录")
async def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    用户登录，返回 JWT Token
    
    - **username**: 用户名
    - **password**: 密码
    """
    # 1. 查询用户
    user = db.query(User).filter(User.username == request.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 2. 验证密码
    if not verify_password(request.password, user.password_hash):
        # 记录失败尝试（审计日志）
        log_audit(
            db=db,
            user_id=user.id,
            username=user.username,
            action="login_failed",
            details={"reason": "密码错误"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 3. 生成 Token
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value}
    )
    
    # 4. 记录成功登录（审计日志）
    log_audit(
        db=db,
        user_id=user.id,
        username=user.username,
        action="login_success",
    )
    
    # 5. 返回 Token
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=user.username,
        role=user.role.value,
        user_id=user.id
    )


@router.get("/me", response_model=UserResponse, summary="获取当前用户信息")
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """
    获取当前登录用户的信息（需要认证）
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role.value,
        created_at=current_user.created_at.isoformat() if current_user.created_at else ""
    )


@router.post("/logout", summary="用户登出")
async def logout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    用户登出（记录审计日志，客户端需清除本地Token）
    """
    log_audit(
        db=db,
        user_id=current_user.id,
        username=current_user.username,
        action="logout",
    )
    return {"message": "登出成功"}