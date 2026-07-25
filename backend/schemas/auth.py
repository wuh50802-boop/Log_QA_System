from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")


class RegisterRequest(BaseModel):
    """注册请求（角色由系统决定，不接受前端传入；如需 admin 由已登录的 admin 通过设角色接口提升）"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=50, description="密码")


class TokenResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="JWT访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    username: str = Field(..., description="用户名")
    role: str = Field(..., description="用户角色")


class UserResponse(BaseModel):
    """用户信息响应（不含密码）"""
    id: int
    username: str
    role: str
    created_at: str


class SetRoleRequest(BaseModel):
    """设角色请求（仅 admin 可调用）"""
    role: str = Field(..., description="目标角色: admin / user")


class SetRoleResponse(BaseModel):
    """设角色响应"""
    success: bool = Field(True, description="是否成功")
    user_id: int = Field(..., description="被修改的用户 ID")
    username: str = Field(..., description="被修改的用户名")
    old_role: str = Field(..., description="修改前角色")
    new_role: str = Field(..., description="修改后角色")
    message: str = Field("", description="提示信息")


class ChangePasswordRequest(BaseModel):
    """修改密码请求（仅自己改自己）"""
    old_password: str = Field(..., min_length=6, max_length=50, description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=50, description="新密码（6-50字符）")


class ChangePasswordResponse(BaseModel):
    """修改密码响应"""
    success: bool = Field(True, description="是否成功")
    message: str = Field("", description="提示信息")


class DeleteUserResponse(BaseModel):
    """删除用户响应"""
    success: bool = Field(True, description="是否成功")
    user_id: int = Field(..., description="被删除的用户 ID")
    username: str = Field(..., description="被删除的用户名")
    deleted_qa_count: int = Field(0, description="级联删除的问答记录数")
    message: str = Field("", description="提示信息")