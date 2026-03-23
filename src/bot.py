import asyncio
import json
import logging
import re
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from src.agent import ApplicationResult, apply_to_job, _load_profile
from src.config import settings
from src.job_validator import extract_job_description, validate_job_match
from src.sheets import ApplicationRecord, append_application

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://\S+")

job_queue: asyncio.Queue = asyncio.Queue()
is_processing = False
queue_task: asyncio.Task | None = None
pending_confirmations: dict[str, tuple[str, Update]] = {}


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
        "1. Extract and analyze the job description\n"
        "2. Validate if the job matches your profile\n"
        "3. Ask for confirmation if it's not a good match\n"
        "4. Open the page and read the job description\n"
        "5. Find and fill the application form using your profile\n"
        "6. Upload your resume if a file upload is present\n"
        "7. Submit the form\n"
        "8. Log the result to your Google Sheet\n\n"
        "*Job Validation*\n"
        "The bot will automatically check if each job matches your:\n"
        "• Skills and experience\n"
        "• Desired roles\n"
        "• Experience level\n"
        "If the match score is below 70%, you'll be asked to confirm before applying.\n\n"
        "*Uploading files*\n"
        "Send a *PDF* file → saved as your resume\n"
        "Send a *JSON* file → saved as your profile",
        parse_mode="Markdown",
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not _is_allowed(user.id):
        await update.message.reply_text("Unauthorized.")
        return

    doc = update.message.document
    mime = doc.mime_type or ""
    name = doc.file_name or ""

    if mime == "application/pdf" or name.lower().endswith(".pdf"):
        dest = Path(settings.resume_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(str(dest))
        await update.message.reply_text(f"Resume saved to `{dest}`.", parse_mode="Markdown")
        logger.info("Resume uploaded by user %s → %s", user.id, dest)

    elif mime == "application/json" or name.lower().endswith(".json"):
        dest = Path(settings.profile_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tg_file = await doc.get_file()
        raw = await tg_file.download_as_bytearray()
        try:
            json.loads(raw)  # validate JSON before saving
        except json.JSONDecodeError as e:
            await update.message.reply_text(f"Invalid JSON: {e}")
            return
        dest.write_bytes(raw)
        await update.message.reply_text(f"Profile saved to `{dest}`.", parse_mode="Markdown")
        logger.info("Profile uploaded by user %s → %s", user.id, dest)

    else:
        await update.message.reply_text(
            "Unsupported file type. Send a *PDF* for your resume or a *JSON* for your profile.",
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

    # Show validation status
    validation_msg = await update.message.reply_text(
        f"Validating job match for:\n{url}\n\n"
        "Extracting job description and checking if it matches your profile...\n\n"
        "*Status:* 🔍 Validating",
        parse_mode="Markdown",
    )

    # Extract job description
    try:
        job_desc = await asyncio.wait_for(
            extract_job_description(url),
            timeout=settings.job_timeout_seconds,
        )
    except asyncio.TimeoutError:
        await validation_msg.edit_text(
            f"Validation timed out after {settings.job_timeout_minutes} minutes.\n\n"
            f"URL: {url}\n\n"
            "*Status:* ❌ Timeout",
            parse_mode="Markdown",
        )
        return
    except Exception as e:
        logger.exception("Failed to extract job description for %s", url)
        await validation_msg.edit_text(
            f"Failed to extract job description.\n\n"
            f"Error: {e}\n\n"
            f"URL: {url}\n\n"
            "*Status:* ❌ Failed",
            parse_mode="Markdown",
        )
        return

    if not job_desc:
        await validation_msg.edit_text(
            f"Could not extract job information from URL.\n\n"
            f"URL: {url}\n\n"
            "*Status:* ❌ Failed",
            parse_mode="Markdown",
        )
        return

    # Validate match against profile
    try:
        profile = _load_profile()
        validation_result = await validate_job_match(job_desc, profile)
    except Exception as e:
        logger.exception("Failed to validate job match for %s", url)
        await validation_msg.edit_text(
            f"Failed to validate job match.\n\n"
            f"Error: {e}\n\n"
            f"Proceeding with application anyway...\n\n"
            "*Status:* ⚠️ Validation Failed",
            parse_mode="Markdown",
        )
        # Continue with application anyway
        validation_result = None

    # If validation succeeded and it's not a match, ask for confirmation
    if validation_result and not validation_result.is_match:
        match_percentage = int(validation_result.match_score * 100)
        concerns_text = "\n".join(f"• {c}" for c in validation_result.concerns[:3])  # Show top 3 concerns
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Apply Anyway", callback_data=f"apply:{url}"),
                InlineKeyboardButton("❌ Skip", callback_data=f"skip:{url}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Store the pending confirmation
        pending_confirmations[url] = (url, update)
        
        await validation_msg.edit_text(
            f"⚠️ *Job may not be a good match* ({match_percentage}% match)\n\n"
            f"*Job:* {job_desc.job_title}\n"
            f"*Company:* {job_desc.company}\n\n"
            f"*Concerns:*\n{concerns_text}\n\n"
            f"*Reasoning:* {validation_result.reasoning}\n\n"
            f"Do you want to apply anyway?",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        return

    # If it's a match or validation failed, proceed with application
    match_info = ""
    if validation_result and validation_result.is_match:
        match_percentage = int(validation_result.match_score * 100)
        key_matches_text = ", ".join(validation_result.key_matches[:5])  # Show top 5 matches
        match_info = f"✅ *Good match!* ({match_percentage}% match)\n{key_matches_text}\n\n"

    queue_size = job_queue.qsize()
    if is_processing:
        status_msg = await validation_msg.edit_text(
            f"{match_info}"
            f"Added to queue (position {queue_size + 1}):\n{url}\n\n"
            f"*Job:* {job_desc.job_title}\n"
            f"*Company:* {job_desc.company}\n\n"
            "Current job is processing, yours will start after.\n\n"
            "*Status:* ⏳ Pending",
            parse_mode="Markdown",
        )
    else:
        status_msg = await validation_msg.edit_text(
            f"{match_info}"
            f"Starting application for:\n{url}\n\n"
            f"*Job:* {job_desc.job_title}\n"
            f"*Company:* {job_desc.company}\n\n"
            "This may take a few minutes...\n\n"
            "*Status:* ⏳ Pending",
            parse_mode="Markdown",
        )

    await job_queue.put((url, update, status_msg))

async def process_queue() -> None:
    global is_processing
    while True:
        try:
            url, update, status_msg = await job_queue.get()
            is_processing = True
            try:
                result = await asyncio.wait_for(
                    apply_to_job(url),
                    timeout=settings.job_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning("Job timed out after %s seconds: %s", settings.job_timeout_seconds, url)
                result = ApplicationResult(
                    success=False,
                    job_title="Unknown",
                    company="Unknown",
                    notes=f"Job timed out after {settings.job_timeout_minutes} minutes",
                    screenshot_path=None,
                )
            await handle_result(result, url, update, status_msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Unexpected error processing %s", url)
            await status_msg.edit_text(
                f"An unexpected error occurred:\n{e}\n\nCheck the logs for details."
            )
        finally:
            job_queue.task_done()
            is_processing = False


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback from inline keyboard buttons."""
    query = update.callback_query
    await query.answer()
    
    if not _is_allowed(update.effective_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    
    data = query.data
    if not data:
        return
    
    action, url = data.split(":", 1)
    
    if action == "skip":
        # Remove from pending confirmations
        pending_confirmations.pop(url, None)
        
        await query.edit_message_text(
            f"Skipped application for:\n{url}\n\n"
            "*Status:* ⏭️ Skipped",
            parse_mode="Markdown",
        )
        logger.info("User skipped application for %s", url)
    
    elif action == "apply":
        # Get the stored update from pending confirmations
        if url not in pending_confirmations:
            await query.edit_message_text(
                f"This confirmation has expired. Please submit the URL again.",
                parse_mode="Markdown",
            )
            return
        
        _, original_update = pending_confirmations.pop(url)
        
        # Extract job info for display
        try:
            job_desc = await extract_job_description(url)
            job_title = job_desc.job_title if job_desc else "Unknown"
            company = job_desc.company if job_desc else "Unknown"
        except Exception:
            job_title = "Unknown"
            company = "Unknown"
        
        queue_size = job_queue.qsize()
        if is_processing:
            status_msg = await query.edit_message_text(
                f"Added to queue (position {queue_size + 1}):\n{url}\n\n"
                f"*Job:* {job_title}\n"
                f"*Company:* {company}\n\n"
                "Current job is processing, yours will start after.\n\n"
                "*Status:* ⏳ Pending",
                parse_mode="Markdown",
            )
        else:
            status_msg = await query.edit_message_text(
                f"Starting application for:\n{url}\n\n"
                f"*Job:* {job_title}\n"
                f"*Company:* {company}\n\n"
                "This may take a few minutes...\n\n"
                "*Status:* ⏳ Pending",
                parse_mode="Markdown",
            )
        
        await job_queue.put((url, original_update, status_msg))
        logger.info("User confirmed application for %s", url)


async def _post_init(application: Application) -> None:
    global queue_task
    logger.info("Starting queue processor")
    queue_task = asyncio.create_task(process_queue())


async def _post_shutdown(application: Application) -> None:
    global queue_task
    if queue_task is not None:
        logger.info("Stopping queue processor")
        queue_task.cancel()
        try:
            await queue_task
        except asyncio.CancelledError:
            pass
        queue_task = None


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
        status="Applied" if result.success else "Failed",
        notes=result.notes or "Applied by AI agent",
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

    if result.success and result.screenshot_path and Path(result.screenshot_path).exists():
        try:
            with open(result.screenshot_path, "rb") as photo:
                await status_msg.reply_photo(photo=photo, caption=reply, parse_mode="Markdown")
            await status_msg.delete()
        except Exception as e:
            logger.warning("Failed to send screenshot: %s", e)
            await status_msg.edit_text(reply, parse_mode="Markdown")
        finally:
            Path(result.screenshot_path).unlink(missing_ok=True)
    else:
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
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
