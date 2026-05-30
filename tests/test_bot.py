"""Unit tests for subscription management."""
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Chat, Message, Update, User
from telegram.ext import ContextTypes


class TestSubscribeUnsubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_new_user(self, clean_db, mock_settings) -> None:
        from src.bot.handlers.subscription import subscribe

        update = _make_mock_update(chat_id=99999)
        context = _make_mock_context()

        await subscribe(update, context)

        assert len(update.message.reply_text.call_args_list) == 1
        reply_text = update.message.reply_text.call_args[0][0]
        assert "Đăng ký thành công" in reply_text

    @pytest.mark.asyncio
    async def test_subscribe_already_subscribed(self, clean_db, mock_settings) -> None:
        from src.bot.handlers.subscription import subscribe
        from src.core.database import get_session
        from src.core.models import Subscription

        # Pre-insert a subscription
        async with get_session() as session:
            session.add(Subscription(chat_id=88888, is_active=True))
            await session.commit()

        update = _make_mock_update(chat_id=88888)
        context = _make_mock_context()

        await subscribe(update, context)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "đã đăng ký" in reply_text

    @pytest.mark.asyncio
    async def test_unsubscribe_active(self, clean_db, mock_settings) -> None:
        from src.bot.handlers.subscription import unsubscribe
        from src.core.database import get_session
        from src.core.models import Subscription

        async with get_session() as session:
            session.add(Subscription(chat_id=77777, is_active=True))
            await session.commit()

        update = _make_mock_update(chat_id=77777)
        context = _make_mock_context()

        await unsubscribe(update, context)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "hủy đăng ký thành công" in reply_text

    @pytest.mark.asyncio
    async def test_unsubscribe_not_subscribed(self, clean_db, mock_settings) -> None:
        from src.bot.handlers.subscription import unsubscribe

        update = _make_mock_update(chat_id=66666)
        context = _make_mock_context()

        await unsubscribe(update, context)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "Chưa đăng ký" in reply_text or "chưa đăng ký" in reply_text


# ── Helper factories ────────────────────────────────────────────────────────────

def _make_mock_update(chat_id: int = 12345) -> Update:
    chat = Chat(id=chat_id, type="private")
    user = User(id=11111, is_bot=False, first_name="Test", last_name="User")
    message = MagicMock(spec=Message)
    message.chat = chat
    message.reply_text = AsyncMock()
    update = Update(update_id=1, message=message)
    update.effective_chat = chat
    update.effective_user = user
    return update


def _make_mock_context() -> ContextTypes.DEFAULT_TYPE:
    ctx = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    ctx.args = []
    return ctx
