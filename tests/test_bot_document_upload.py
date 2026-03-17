import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


def _make_fake_telegram():
    """Return a minimal fake telegram package tree."""
    telegram = types.ModuleType("telegram")
    telegram.Update = object
    telegram.InputMediaPhoto = object

    ContextTypes = MagicMock()
    ContextTypes.DEFAULT_TYPE = None

    ext = types.ModuleType("telegram.ext")
    ext.Application = MagicMock()
    ext.CommandHandler = MagicMock()
    ext.ContextTypes = ContextTypes
    ext.MessageHandler = MagicMock()
    ext.filters = MagicMock()

    sys.modules["telegram"] = telegram
    sys.modules["telegram.ext"] = ext
    return telegram, ext


def _make_fake_deps(resume_path: str, profile_path: str, allowed_ids: list[int]):
    fake_agent = types.ModuleType("src.agent")
    fake_agent.ApplicationResult = object
    fake_agent.apply_to_job = AsyncMock()
    sys.modules["src.agent"] = fake_agent

    fake_sheets = types.ModuleType("src.sheets")
    fake_sheets.ApplicationRecord = object
    fake_sheets.append_application = MagicMock()
    sys.modules["src.sheets"] = fake_sheets

    fake_config = types.ModuleType("src.config")
    fake_config.settings = types.SimpleNamespace(
        resume_path=resume_path,
        profile_path=profile_path,
        allowed_user_ids=allowed_ids,
        telegram_bot_token="test-token",
        log_file=None,
        job_timeout_seconds=600,
        job_timeout_minutes=10,
    )
    sys.modules["src.config"] = fake_config


def _make_update(user_id: int, mime_type: str, file_name: str, file_bytes: bytes):
    """Build a minimal mock Update with a document."""
    fake_tg_file = MagicMock()
    fake_tg_file.download_to_drive = AsyncMock()
    fake_tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(file_bytes))

    doc = MagicMock()
    doc.mime_type = mime_type
    doc.file_name = file_name
    doc.get_file = AsyncMock(return_value=fake_tg_file)

    message = MagicMock()
    message.document = doc
    message.reply_text = AsyncMock()

    user = MagicMock()
    user.id = user_id

    update = MagicMock()
    update.effective_user = user
    update.message = message

    return update, fake_tg_file


class DocumentUploadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Wipe cached modules so each test gets a fresh import
        for mod in ("src.bot", "src.agent", "src.config", "src.sheets",
                    "telegram", "telegram.ext"):
            sys.modules.pop(mod, None)

        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.resume_path = str(tmp / "resume.pdf")
        self.profile_path = str(tmp / "profile.json")

        _make_fake_telegram()
        _make_fake_deps(self.resume_path, self.profile_path, allowed_ids=[])
        self.bot = importlib.import_module("src.bot")

    def tearDown(self):
        self._tmpdir.cleanup()
        for mod in ("src.bot", "src.agent", "src.config", "src.sheets",
                    "telegram", "telegram.ext"):
            sys.modules.pop(mod, None)

    # ------------------------------------------------------------------
    # PDF upload
    # ------------------------------------------------------------------

    async def test_pdf_by_mime_type_saves_resume(self):
        update, tg_file = _make_update(
            user_id=1,
            mime_type="application/pdf",
            file_name="my_resume.pdf",
            file_bytes=b"%PDF-1.4 fake",
        )
        await self.bot.handle_document(update, None)

        tg_file.download_to_drive.assert_awaited_once_with(self.resume_path)
        update.message.reply_text.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "resume" in reply.lower()

    async def test_pdf_by_extension_saves_resume(self):
        update, tg_file = _make_update(
            user_id=1,
            mime_type="application/octet-stream",
            file_name="cv.pdf",
            file_bytes=b"%PDF fake",
        )
        await self.bot.handle_document(update, None)

        tg_file.download_to_drive.assert_awaited_once_with(self.resume_path)

    # ------------------------------------------------------------------
    # JSON / profile upload
    # ------------------------------------------------------------------

    async def test_valid_json_by_mime_type_saves_profile(self):
        payload = json.dumps({"full_name": "Ada Lovelace", "email": "ada@example.com"}).encode()
        update, _ = _make_update(
            user_id=1,
            mime_type="application/json",
            file_name="profile.json",
            file_bytes=payload,
        )
        await self.bot.handle_document(update, None)

        saved = Path(self.profile_path).read_bytes()
        assert json.loads(saved)["full_name"] == "Ada Lovelace"
        reply = update.message.reply_text.call_args[0][0]
        assert "profile" in reply.lower()

    async def test_valid_json_by_extension_saves_profile(self):
        payload = json.dumps({"full_name": "Grace Hopper"}).encode()
        update, _ = _make_update(
            user_id=1,
            mime_type="text/plain",
            file_name="profile.json",
            file_bytes=payload,
        )
        await self.bot.handle_document(update, None)

        saved = json.loads(Path(self.profile_path).read_bytes())
        assert saved["full_name"] == "Grace Hopper"

    async def test_invalid_json_replies_with_error_and_does_not_save(self):
        update, _ = _make_update(
            user_id=1,
            mime_type="application/json",
            file_name="bad.json",
            file_bytes=b"{not valid json",
        )
        await self.bot.handle_document(update, None)

        assert not Path(self.profile_path).exists()
        reply = update.message.reply_text.call_args[0][0]
        assert "invalid json" in reply.lower()

    # ------------------------------------------------------------------
    # Unsupported file type
    # ------------------------------------------------------------------

    async def test_unsupported_mime_replies_with_hint(self):
        update, tg_file = _make_update(
            user_id=1,
            mime_type="image/png",
            file_name="photo.png",
            file_bytes=b"\x89PNG",
        )
        await self.bot.handle_document(update, None)

        tg_file.download_to_drive.assert_not_awaited()
        reply = update.message.reply_text.call_args[0][0]
        assert "pdf" in reply.lower()
        assert "json" in reply.lower()

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    async def test_unauthorized_user_is_rejected(self):
        # Restrict to user 42 only
        sys.modules["src.config"].settings.allowed_user_ids = [42]

        update, tg_file = _make_update(
            user_id=99,
            mime_type="application/pdf",
            file_name="resume.pdf",
            file_bytes=b"%PDF fake",
        )
        await self.bot.handle_document(update, None)

        tg_file.download_to_drive.assert_not_awaited()
        update.message.reply_text.assert_awaited_once_with("Unauthorized.")

    async def test_authorized_user_is_allowed(self):
        sys.modules["src.config"].settings.allowed_user_ids = [7]

        update, tg_file = _make_update(
            user_id=7,
            mime_type="application/pdf",
            file_name="resume.pdf",
            file_bytes=b"%PDF fake",
        )
        await self.bot.handle_document(update, None)

        tg_file.download_to_drive.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
