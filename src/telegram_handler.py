import os
import io
import tempfile
import asyncio
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from .agent_loop import AgentLoop

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
REPORT_CHAR_THRESHOLD = 2000  # Responses longer than this are sent as a .md file


class TelegramHandler:
    """Connects the Agent Loop to the Telegram API.
    
    Supports:
    - plain text
    - PDF documents
    - Markdown (.md) documents
    - voice/audio notes (transcribed via Whisper)
    - report (.md) file output for long structured answers
    - audio output when explicitly requested
    """

    def __init__(self, token: str, allowed_users: list, agent_loop: AgentLoop):
        self.token = token
        self.allowed_users = [str(u) for u in allowed_users]
        self.agent_loop = agent_loop
        # Reuse the same OpenAI client for TTS / transcription
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # ─────────────────────────────────────────────
    # Authorization
    # ─────────────────────────────────────────────

    async def _check_access(self, update: Update) -> bool:
        user_id = str(update.effective_user.id)
        if user_id not in self.allowed_users:
            await update.message.reply_text(
                "⛔ Acesso negado. Seu User ID do Telegram não está na lista de usuários autorizados."
            )
            return False
        return True

    # ─────────────────────────────────────────────
    # Commands
    # ─────────────────────────────────────────────

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return
        await update.message.reply_text(
            "👋 Olá! Eu sou o *CloseClawdio*, seu assistente corporativo especializado em FP&A e orçamentos.\n\n"
            "Você pode me enviar:\n"
            "• 📝 Perguntas em texto\n"
            "• 📄 Relatórios em PDF ou Markdown\n"
            "• 🎤 Notas de voz\n\n"
            "Como posso ajudar com a visão financeira hoje?",
            parse_mode="Markdown"
        )

    async def reset_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return
        user_id = str(update.effective_user.id)
        self.agent_loop.memory.clear_history(user_id)
        await update.message.reply_text(
            "✅ Contexto reiniciado. Pode começar uma nova análise!"
        )

    # ─────────────────────────────────────────────
    # Input: Plain Text
    # ─────────────────────────────────────────────

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_access(update):
            return
        user_message = update.message.text
        user_id = str(update.effective_user.id)
        await self._process_and_reply(update, context, user_id, user_message, source_type="text")

    # ─────────────────────────────────────────────
    # Input: Documents (PDF / Markdown)
    # ─────────────────────────────────────────────

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Auth first — never download before checking
        if not await self._check_access(update):
            return

        doc = update.message.document
        filename = doc.file_name or ""
        caption = update.message.caption or ""
        user_id = str(update.effective_user.id)

        # Determine document type
        is_pdf = filename.lower().endswith(".pdf")
        is_md = filename.lower().endswith(".md") or filename.lower().endswith(".markdown")

        if not is_pdf and not is_md:
            await update.message.reply_text(
                "⚠️ Formato não suportado. Por favor envie um arquivo PDF ou Markdown (.md)."
            )
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        tmp_path = None
        try:
            # Download to a temp file
            tg_file = await context.bot.get_file(doc.file_id)
            suffix = ".pdf" if is_pdf else ".md"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
                await tg_file.download_to_drive(tmp_path)

            # Extract text
            if is_pdf:
                text = self._extract_pdf_text(tmp_path)
            else:
                with open(tmp_path, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()

            if not text.strip():
                await update.message.reply_text(
                    "⚠️ Não foi possível extrair texto deste documento. Verifique se o arquivo não está vazio ou protegido."
                )
                return

            # Build normalized user message
            source_label = f"[Arquivo: {filename}]"
            combined = f"{source_label}\n\n{caption}\n\n{text}".strip() if caption else f"{source_label}\n\n{text}".strip()

            await self._process_and_reply(update, context, user_id, combined, source_type="document", filename=filename)

        except Exception as e:
            print(f"Document handling error: {e}")
            await update.message.reply_text(
                "⚠️ Falha ao processar o documento. Tente novamente ou envie o conteúdo como texto."
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _extract_pdf_text(self, path: str) -> str:
        from pypdf import PdfReader
        reader = PdfReader(path)
        pages = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                pages.append(extracted)
        return "\n\n".join(pages)

    # ─────────────────────────────────────────────
    # Input: Voice / Audio Notes
    # ─────────────────────────────────────────────

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Auth first
        if not await self._check_access(update):
            return

        user_id = str(update.effective_user.id)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_audio")

        # Determine if audio or voice
        media = update.message.voice or update.message.audio
        if not media:
            await update.message.reply_text("⚠️ Não consegui identificar o áudio.")
            return

        tmp_path = None
        try:
            tg_file = await context.bot.get_file(media.file_id)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp_path = tmp.name
                await tg_file.download_to_drive(tmp_path)

            # Transcribe via Whisper
            with open(tmp_path, "rb") as audio_file:
                transcription = self.openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="pt"
                )
            text = transcription.text.strip()

            if not text:
                await update.message.reply_text("⚠️ O áudio estava vazio ou não foi possível transcrever.")
                return

            await update.message.reply_text(f"🎤 _Transcrição:_ {text}", parse_mode="Markdown")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

            await self._process_and_reply(
                update, context, user_id, text,
                source_type="audio",
                request_audio_reply=self._wants_audio_reply(text)
            )

        except Exception as e:
            print(f"Voice handling error: {e}")
            await update.message.reply_text(
                "⚠️ Falha ao processar o áudio. Tente enviar a pergunta como texto."
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _wants_audio_reply(self, text: str) -> bool:
        """Detect if the user explicitly requested an audio/voice response."""
        keywords = ["em áudio", "em voz", "responda em áudio", "voice summary", "audio summary", "me responda em voz"]
        return any(k in text.lower() for k in keywords)

    # ─────────────────────────────────────────────
    # Core processing pipeline
    # ─────────────────────────────────────────────

    async def _process_and_reply(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: str,
        user_message: str,
        source_type: str = "text",
        filename: str = None,
        request_audio_reply: bool = False
    ):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

        # Check for explicit audio reply request in plain text too
        if source_type == "text" and self._wants_audio_reply(user_message):
            request_audio_reply = True

        # Run agent (blocking IO — run in thread executor)
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(
            None,
            self.agent_loop.process_message,
            user_id,
            user_message
        )

        # Determine output mode
        if request_audio_reply:
            await self._send_audio_response(update, context, answer)
        elif len(answer) > REPORT_CHAR_THRESHOLD and self._looks_like_report(answer):
            await self._send_as_report(update, context, answer)
        else:
            await self._send_text(update, answer)

    # ─────────────────────────────────────────────
    # Output: Text (chunked if needed)
    # ─────────────────────────────────────────────

    async def _send_text(self, update: Update, answer: str):
        """Send text, chunked at 4000 chars to respect Telegram limits."""
        if len(answer) <= 4000:
            try:
                await update.message.reply_text(answer, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(answer)  # Fallback without parsing
        else:
            for i in range(0, len(answer), 4000):
                try:
                    await update.message.reply_text(answer[i:i+4000], parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(answer[i:i+4000])

    def _looks_like_report(self, text: str) -> bool:
        """Heuristic: if the answer has multiple markdown headers, treat as report."""
        return text.count("\n#") >= 2 or text.count("\n##") >= 2

    # ─────────────────────────────────────────────
    # Output: Markdown Report File
    # ─────────────────────────────────────────────

    async def _send_as_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE, answer: str):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as tmp:
                tmp_path = tmp.name
                tmp.write(answer)
            with open(tmp_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename="relatorio_clawdio.md",
                    caption="📊 Relatório gerado pelo CloseClawdio"
                )
        except Exception as e:
            print(f"Report output error: {e}")
            await self._send_text(update, answer)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ─────────────────────────────────────────────
    # Output: Audio (TTS via OpenAI)
    # ─────────────────────────────────────────────

    async def _send_audio_response(self, update: Update, context: ContextTypes.DEFAULT_TYPE, answer: str):
        tmp_path = None
        try:
            # Prepare spoken-friendly version (strip markdown artifacts)
            spoken_text = answer.replace("**", "").replace("*", "").replace("#", "").replace("`", "")
            # Limit to ~800 chars for voice — keep main conclusion + recommendation
            if len(spoken_text) > 800:
                spoken_text = spoken_text[:800] + "..."

            tts_response = self.openai_client.audio.speech.create(
                model="tts-1",
                voice="onyx",
                input=spoken_text
            )
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp_path = tmp.name
                tts_response.stream_to_file(tmp_path)

            with open(tmp_path, "rb") as f:
                await context.bot.send_voice(
                    chat_id=update.effective_chat.id,
                    voice=f,
                    caption="🔊 Resumo em áudio — CloseClawdio"
                )
        except Exception as e:
            print(f"TTS error: {e}")
            # Graceful fallback to text
            await self._send_text(update, answer)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ─────────────────────────────────────────────
    # App builder
    # ─────────────────────────────────────────────

    def build_app(self) -> Application:
        app = (
            Application.builder()
            .token(self.token)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .get_updates_connect_timeout(30.0)
            .get_updates_read_timeout(30.0)
            .build()
        )
        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("reset", self.reset_command))
        # Document handler (PDF / Markdown)
        app.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        # Voice and audio
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.handle_voice))
        # Plain text (must be last to not catch commands)
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        return app
