#编写认证 API 路由
from fastapi import APIRouter, HTTPException, Depends, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import Optional
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
    UserResponse,
    SetRoleRequest,
    SetRoleResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    DeleteUserResponse,
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
    注册新用户（角色固定为 user，不接受前端传入 role）

    - **username**: 用户名（3-50字符，唯一）
    - **password**: 密码（6-50字符）

    注册后默认为普通用户（user）；如需 admin 角色，
    由已登录的 admin 调用 `PATCH /api/auth/users/{id}/role` 提升。
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

    # 3. 创建用户（角色强制为 USER，忽略任何外部传入的 role 字段）
    new_user = User(
        username=request.username,
        password_hash=hashed_password,
        role=UserRole.USER,
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
        details={"role": new_user.role.value, "note": "self-registered, forced user role"}
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


@router.post(
    "/me/password",
    response_model=ChangePasswordResponse,
    summary="修改自己的密码",
)
async def change_my_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    修改当前登录用户自己的密码（需提供旧密码验证）。

    - **old_password**: 旧密码（必须匹配）
    - **new_password**: 新密码（6-50字符，不能与旧密码相同）

    所有登录用户都可调用，只能改自己的密码。
    """
    # 1. 验证旧密码
    if not verify_password(request.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码错误",
        )

    # 2. 新旧密码不能相同
    if request.old_password == request.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与旧密码相同",
        )

    # 3. 更新密码
    current_user.password_hash = get_password_hash(request.new_password)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存密码失败: {str(e)}",
        )

    # 4. 审计日志
    try:
        log_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="change_password",
            resource="users",
        )
    except Exception:
        pass

    return ChangePasswordResponse(
        success=True,
        message="密码修改成功，下次登录请使用新密码",
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


# ============================================
# 管理员专用接口
# ============================================

def _require_admin(user: User) -> None:
    """校验当前用户是否为 admin，否则抛 403"""
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足：仅管理员可执行此操作",
        )


@router.patch(
    "/users/{user_id}/role",
    response_model=SetRoleResponse,
    summary="修改用户角色（仅 admin）",
)
async def set_user_role(
    user_id: int,
    request: SetRoleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    修改指定用户的角色（admin ↔ user）。**仅 admin 可调用**。

    - **user_id**: 被修改的用户 ID（URL 路径参数）
    - **role**: 目标角色，`admin` 或 `user`

    安全约束：
    - 非 admin 调用直接返回 403
    - 不允许修改自己的角色（避免唯一管理员把自己降级后无人管理）
    """
    # 1. 鉴权：仅 admin
    _require_admin(current_user)

    # 2. 校验目标角色合法性
    try:
        new_role = UserRole(request.role)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"无效的角色: {request.role}，可选: admin / user",
        )

    # 3. 查询目标用户
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户 ID={user_id} 不存在",
        )

    # 4. 不允许修改自己的角色
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不允许修改自己的角色（避免唯一管理员被降级后无人管理）",
        )

    old_role = target.role.value if target.role else "user"

    # 5. 更新角色
    target.role = new_role
    try:
        db.commit()
        db.refresh(target)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存角色失败: {str(e)}",
        )

    # 6. 审计日志
    try:
        log_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="set_role",
            resource="users",
            details={
                "target_user_id": target.id,
                "target_username": target.username,
                "old_role": old_role,
                "new_role": new_role.value,
            },
        )
    except Exception as e:
        # 审计日志失败不影响主流程
        pass

    action_text = "提升为管理员" if new_role == UserRole.ADMIN else "降级为普通用户"
    logger_msg = (
        f"admin {current_user.username} 将用户 {target.username} 的角色 "
        f"从 {old_role} 改为 {new_role.value}"
    )
    print(logger_msg)

    return SetRoleResponse(
        success=True,
        user_id=target.id,
        username=target.username,
        old_role=old_role,
        new_role=new_role.value,
        message=f"已将用户 {target.username} {action_text}",
    )


@router.get(
    "/users",
    summary="查询所有用户列表（仅 admin，支持用户名模糊搜索）",
)
async def list_users(
    username: Optional[str] = Query(None, description="按用户名模糊搜索（包含匹配，大小写不敏感）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询所有用户列表（含角色信息），**仅 admin 可调用**。

    - **username**: 可选，按用户名模糊搜索（包含匹配）。不传则返回全部。

    用于 admin 在用户管理页面查看用户、搜索特定用户。
    """
    from schemas.auth import UserResponse

    _require_admin(current_user)

    query = db.query(User)
    if username and username.strip():
        # 大小写不敏感的包含匹配
        keyword = f"%{username.strip().lower()}%"
        query = query.filter(func.lower(User.username).like(keyword))
    users = query.order_by(User.id.asc()).all()

    return {
        "success": True,
        "total": len(users),
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "role": u.role.value if u.role else "user",
                "created_at": u.created_at.isoformat() if u.created_at else "",
            }
            for u in users
        ],
    }


@router.delete(
    "/users/{user_id}",
    response_model=DeleteUserResponse,
    summary="删除用户（仅 admin，级联删除其问答记录）",
)
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除指定用户，**仅 admin 可调用**。

    安全约束：
    - **不允许删除自己**（避免 admin 误删自己账号）
    - **不允许删除最后一个 admin**（避免无人管理系统）
    - **级联删除**该用户的全部问答历史（qa_history），保留审计日志（audit_log）便于追溯

    返回字段：
    - **deleted_qa_count**: 级联删除的问答记录数
    """
    from models.qa_history import QAHistory

    # 1. 鉴权：仅 admin
    _require_admin(current_user)

    # 2. 不允许删除自己
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不允许删除自己",
        )

    # 3. 查询目标用户
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"用户 ID={user_id} 不存在",
        )

    # 4. 保护最后一个 admin
    if target.role == UserRole.ADMIN:
        admin_count = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN)
            .count()
        )
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不允许删除最后一个管理员（避免无人管理系统）",
            )

    # 5. 级联删除该用户的问答历史
    deleted_qa_count = 0
    try:
        deleted_qa_count = (
            db.query(QAHistory)
            .filter(QAHistory.user_id == user_id)
            .delete(synchronize_session=False)
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除用户问答历史失败: {str(e)}",
        )

    # 6. 删除用户本身
    try:
        db.delete(target)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除用户失败: {str(e)}",
        )

    # 7. 审计日志（admin 自己的行为，仍记录以便追溯）
    try:
        log_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="delete_user",
            resource="users",
            details={
                "deleted_user_id": user_id,
                "deleted_username": target.username,
                "deleted_qa_count": deleted_qa_count,
            },
        )
    except Exception:
        pass

    return DeleteUserResponse(
        success=True,
        user_id=user_id,
        username=target.username,
        deleted_qa_count=deleted_qa_count,
        message=f"已删除用户 {target.username}（同时清理 {deleted_qa_count} 条问答记录）",
    )