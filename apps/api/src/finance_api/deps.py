"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from finance_api.container import AppContainer
from finance_api.security import client_ip, enforce_same_origin, session_token_from
from finance_core.auth.schemas import ClientInfo, Principal
from finance_core.auth.service import AuthService
from finance_core.errors import AuthenticationError
from finance_core.observability import request_id_var, user_id_var
from finance_core.users.context import UserContext
from finance_core.users.service import UserService


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async with container.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_principal(request: Request, container: ContainerDep) -> Principal:
    token, method = session_token_from(request, container.settings)
    if not token:
        raise AuthenticationError("Sign in to continue.")
    # A short-lived session of its own: streaming endpoints must not hold a pooled
    # connection for the duration of a chat turn just because they authenticated.
    async with container.session_factory() as session:
        principal = await AuthService(session, container.settings, container.clock).authenticate(
            token
        )
    if principal is None:
        raise AuthenticationError(
            "Your session has expired. Please sign in again.", code="session_expired"
        )
    if method == "cookie":
        enforce_same_origin(request, container.settings)
    user_id_var.set(str(principal.user_id))
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_user_context(principal: PrincipalDep, session: SessionDep) -> UserContext:
    return await UserService(session).context(principal.user_id)


UserContextDep = Annotated[UserContext, Depends(get_user_context)]


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(ip_address=client_ip(request), user_agent=request.headers.get("user-agent"))


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]


def get_request_id() -> str | None:
    return request_id_var.get()


RequestIdDep = Annotated[str | None, Depends(get_request_id)]
