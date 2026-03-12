import asyncio
import logging
import re

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.agent import apply_to_job
from src.config import settings
from src.sheets import ApplicationRecord, append_application

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://\S+")

job_queue: asyncio.Queue = asyncio.Queue()
is_processing = False


def _is_allowed(user_id: int) -> bool:
    allowed = settings.allowed_user_ids
    if not allowed:
        return True
    return user_id in allowed


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text(
        "Job Applier bot ready.\n\n"
        "Send me a job posting URL and I will apply on your behalf, then update your tracking sheet.\n\n"
        "Example:\n  https://example.com/jobs/senior-engineer"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_allowed(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    await update.message.reply_text(
        "*Commands*\n"
        "/start — Show welcome message\n"
        "/help  — Show this message\n\n"
        "*Usage*\n"
        "Send any message containing a job URL and the bot will:\n"
        "1. Open the page and read the job description\n"
        "2. Find and fill the application form using your profile\n"
        "3. Upload your resume if a file upload is present\n"
        "4. Submit the form\n"
        "5. Log the result to your Google Sheet",
        parse_mode="Markdown",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Unauthorized.")
        return

    text = update.message.text or ""
    urls = URL_PATTERN.findall(text)

    if not urls:
        await update.message.reply_text(
            "No URL found in your message. Send me a job posting URL to get started."
        )
        return

    if len(urls) > 1:
        await update.message.reply_text(
            "Please send one URL at a time."
        )
        return

    url = urls[0]
    logger.info("Received job URL from user %s: %s", user.id, url)

    queue_size = job_queue.qsize()
    if is_processing:
        status_msg = await update.message.reply_text(
            f"Added to queue (position {queue_size + 1}):\n{url}\n\n"
            "Current job is processing, yours will start after."
        )
    else:
        status_msg = await update.message.reply_text(
            f"Starting application for:\n{url}\n\nThis may take a few minutes..."
        )

    await job_queue.put((url, update, status_msg))

async def process_queue(application: Application) -> None:
    global is_processing
    while True:
        url, update, status_msg = await job_queue.get()
        is_processing = True
        try:
            result = await apply_to_job(url)
            await handle_result(result, url, update, status_msg)
        except Exception as e:
            logger.exception("Unexpected error processing %s", url)
            await status_msg.edit_text(
                f"An unexpected error occurred:\n{e}\n\nCheck the logs for details."
            )
        finally:
            is_processing = False


async def handle_result(result, url: str, update: Update, status_msg) -> None:
    if not result.company or result.company == "Unknown" or not result.job_title or result.job_title == "Unknown":
        logger.warning("Skipping sheet update: could not extract company/title from %s", url)
        status = "✅ Applied" if result.success else "❌ Failed"
        await status_msg.edit_text(
            f"Application {'submitted' if result.success else 'failed'} but could not extract company/name — not logging to sheet.\n\n"
            f"Job: {result.job_title}\n"
            f"Company: {result.company}\n"
            f"Reason: {result.notes}\n\n"
            f"*Status:* {status}",
            parse_mode="Markdown",
        )
        return

    record = ApplicationRecord(
        job_title=result.job_title,
        url=url,
        company=result.company,
        status="applied" if result.success else "failed",
    )
    try:
        append_application(record)
        sheet_status = "Logged to Google Sheet."
    except Exception as e:
        logger.error("Failed to write to sheet: %s", e)
        sheet_status = f"Warning: could not update Google Sheet — {e}"

    if result.success:
        reply = (
            f"Application submitted!\n\n"
            f"*Job:* {result.job_title}\n"
            f"*Company:* {result.company}\n"
            f"*Notes:* {result.notes}\n\n"
            f"*Status:* ✅ Applied\n\n"
            f"{sheet_status}"
        )
    else:
        reply = (
            f"Application failed.\n\n"
            f"*Job:* {result.job_title}\n"
            f"*Company:* {result.company}\n"
            f"*Reason:* {result.notes}\n\n"
            f"*Status:* ❌ Failed\n\n"
            f"{sheet_status}"
        )

    await status_msg.edit_text(reply, parse_mode="Markdown")


def main() -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    log_file = settings.log_file
    if log_file:
        from logging.handlers import RotatingFileHandler
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_file,
                maxBytes=5 * 1024 * 1024,  # 5 MB per file
                backupCount=3,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        handlers=handlers,
    )

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async def run():
        async with app:
            queue_task = asyncio.create_task(process_queue(app))
            polling_task = asyncio.create_task(app.updater.start_polling())
            try:
                await asyncio.gather(queue_task, polling_task)
            except asyncio.CancelledError:
                queue_task.cancel()
                polling_task.cancel()

    logger.info("Bot polling started")
    asyncio.run(run())


if __name__ == "__main__":
    main()
