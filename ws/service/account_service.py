"""注册与登录时的商城账号绑定。

商城号只能由中台开户分配（POST /shop/users），再记进 commerce_accounts。
之前「用户名像 u1001 就当商城号、否则回落 u1001」的规则已删除：
它让任何人注册一个 u1002 就能冒领别人的订单与地址，也让其余账号全部共用 u1001。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class AccountError(Exception):
    """注册/登录里说给用户听的错误（如用户名已存在）。"""


class AccountService:
    def __init__(self, users, accounts,
                 provision: Callable[[str], Awaitable[str]]) -> None:
        self.users = users
        self.accounts = accounts
        self.provision = provision

    async def register(self, username: str, password_hash: str) -> str:
        """建客服账号并开一个新的商城账号，返回商城号。调用方负责提交/回滚事务。"""
        if await self.users.get_by_username(username):
            raise AccountError("该用户名已被注册")
        await self.users.create(username, password_hash)
        return await self.ensure_account(username)

    async def ensure_account(self, username: str) -> str:
        """取已绑定的商城号；改造前注册的账号没有绑定，就在此时开一个新号。"""
        cuid = await self.accounts.get_cuid(username)
        if cuid:
            return cuid
        cuid = await self.provision(username)
        await self.accounts.bind(username, cuid)
        return cuid
