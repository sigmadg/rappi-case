"""
Envío de mensajes vía python-telegram-bot (Bot API oficial).

Secciones:
  - Credenciales: leen TELEGRAM_* del entorno; rechazan tokens “placeholder” del .env.example.
  - send_message: API síncrona (internamente asyncio.run) para el resto del pipeline.
  - ping_telegram_async: diagnóstico sin pasar por el motor (run_agent --test-telegram).
"""

from __future__ import annotations  # str | None en firmas

import asyncio  # Bot API es async; la capa sync envuelve con asyncio.run
import os  # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

from telegram import Bot  # Cliente oficial
from telegram.error import Forbidden, InvalidToken, TelegramError  # Errores tipificados

# Tokens de ejemplo del repo — no deben usarse en producción (falla explícita).
_PLACEHOLDER_TOKENS = frozenset(
    {
        "",
        "your_bot_token_here",
        "changeme",
        "paste_token_here",
    }
)


def _is_placeholder_token(value: str) -> bool:
    if not value:
        return True
    return value.lower() in {p.lower() for p in _PLACEHOLDER_TOKENS if p}


def _telegram_credentials_ok() -> tuple[str | None, str | None]:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if _is_placeholder_token(token) or not chat_id:
        return None, None  # Ping deshabilitado hasta configurar bien .env
    return token, chat_id


def _resolve_credentials(
    token_override: str | None, chat_id_override: str | None
) -> tuple[str, str]:
    """Combina overrides con variables de entorno; rechaza token placeholder."""
    raw_t = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    raw_c = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    token = (token_override or raw_t or "").strip()
    chat_id = (chat_id_override or raw_c or "").strip()
    if _is_placeholder_token(token) or not chat_id:
        raise RuntimeError(
            "Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en caso_tecnico/.env "
            "(copia desde .env.example y pega el token real de @BotFather; no dejes 'your_bot_token_here')."
        )
    return token, chat_id


async def _send_async(text: str, token: str, chat_id: str) -> None:
    """Un envío; errores comunes traducidos a RuntimeError con mensaje accionable."""
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except InvalidToken as e:
        raise RuntimeError(
            "Token de bot inválido o revocado. Genera uno nuevo en @BotFather y actualiza .env"
        ) from e
    except Forbidden as e:
        raise RuntimeError(
            "Telegram Forbidden: el bot no puede escribir en ese chat. "
            "En un CANAL: añade el bot como administrador con permiso de publicar mensajes. "
            "Comprueba TELEGRAM_CHAT_ID (prueba @nombre_canal o el id -100...)."
        ) from e
    except TelegramError as e:
        raise RuntimeError(
            f"Error Telegram API ({type(e).__name__}): {e}. "
            f"chat_id usado: {chat_id!r}"
        ) from e


def send_message(text: str, *, token: str | None = None, chat_id: str | None = None) -> None:
    t, c = _resolve_credentials(token, chat_id)
    asyncio.run(_send_async(text, t, str(c)))  # Punto de entrada síncrono para pipeline/Django


async def ping_telegram_async() -> str:
    """
    Envía un mensaje de prueba y devuelve texto de diagnóstico (bot username, chat_id).
    """
    token, chat_id = _telegram_credentials_ok()
    if not token or not chat_id:
        raise RuntimeError(
            "Edita caso_tecnico/.env: TELEGRAM_BOT_TOKEN=<token de @BotFather> y "
            "TELEGRAM_CHAT_ID=@tu_canal (o id -100...). Si no existe .env: cp .env.example .env"
        )
    bot = Bot(token=token)
    me = await bot.get_me()  # Verifica token y obtiene @username
    msg = (
        f"✅ Ping desde caso_tecnico (Módulo 3).\n"
        f"Bot: @{me.username}\n"
        f"Si lees esto en el canal/chat correcto, token y chat_id están bien."
    )
    await _send_async(msg, token, str(chat_id))
    return f"Enviado OK → chat_id={chat_id!r} | bot @{me.username}"
