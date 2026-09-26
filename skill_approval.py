import asyncio
import json
import re
import time
from typing import Any, Dict

from gateway.session_context import get_session_env
from tools import write_approval as wa
from tools.skill_manager_tool import apply_skill_pending


TRIGGERS = {
    "update skill",
    "simpan skill",
}

STATE_KEY = "skill_update_candidates"
PREAPPROVAL_KEY = "skill_update_preapprovals"

PREAPPROVAL_TTL_SECONDS = 180
CANDIDATE_TTL_SECONDS = 7 * 24 * 60 * 60


REQUEST_SKILL_APPROVAL = {
    "name": "request_skill_approval",
    "description": (
        "Show the authorized Telegram user native Update Skill / Batal buttons "
        "for one validated staged skill write. "
        "Call this only after skill_manage returns "
        "ready_for_human_approval=true. "
        "Do not use clarify for Ardiles skill approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pending_id": {
                "type": "string",
                "description": (
                    "The pending_id returned by skill_manage "
                    "after Ardiles validation succeeds."
                ),
            },
        },
        "required": [
            "pending_id"
        ],
    },
}


def _normalize_text(value: Any) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .split()
    )


def _platform_name(value: Any) -> str:
    raw = getattr(
        value,
        "value",
        value,
    )

    return str(
        raw or ""
    ).strip().lower()


def _json_result(value: Any) -> Dict[str, Any]:
    if isinstance(
        value,
        dict
    ):
        return dict(value)

    if not isinstance(
        value,
        str
    ):
        return {}

    try:
        parsed = json.loads(
            value
        )
    except Exception:
        return {}

    if isinstance(
        parsed,
        dict
    ):
        return parsed

    return {}


class SkillApproval:
    def __init__(
        self,
        ctx
    ):
        self.ctx = ctx

        self.telegram_application = None
        self.telegram_loop = None

    # =====================================================
    # Authorization
    # =====================================================

    def authorized_ids(
        self
    ) -> set[str]:
        raw = self.ctx.get_config(
            "skill_update_telegram_ids",
            ""
        )

        if isinstance(
            raw,
            list
        ):
            parts = raw
        else:
            parts = re.split(
                r"[\s,;]+",
                str(raw or "")
            )

        return {
            str(item).strip()
            for item in parts
            if str(item).strip().isdigit()
        }

    def session_identity(
        self
    ) -> Dict[str, str]:
        platform = (
            get_session_env(
                "HERMES_SESSION_PLATFORM",
                ""
            )
            or
            get_session_env(
                "HERMES_SESSION_SOURCE",
                ""
            )
        )

        return {
            "platform":
                _platform_name(
                    platform
                ),

            "user_id":
                str(
                    get_session_env(
                        "HERMES_SESSION_USER_ID",
                        ""
                    )
                    or ""
                ).strip(),

            "chat_id":
                str(
                    get_session_env(
                        "HERMES_SESSION_CHAT_ID",
                        ""
                    )
                    or ""
                ).strip(),

            "thread_id":
                str(
                    get_session_env(
                        "HERMES_SESSION_THREAD_ID",
                        ""
                    )
                    or ""
                ).strip(),

            "session_id":
                str(
                    get_session_env(
                        "HERMES_SESSION_ID",
                        ""
                    )
                    or ""
                ).strip(),
        }

    def event_identity(
        self,
        event
    ) -> Dict[str, str]:
        source = getattr(
            event,
            "source",
            None
        )

        return {
            "platform":
                _platform_name(
                    getattr(
                        source,
                        "platform",
                        ""
                    )
                ),

            "user_id":
                str(
                    getattr(
                        source,
                        "user_id",
                        ""
                    )
                    or ""
                ).strip(),

            "chat_id":
                str(
                    getattr(
                        source,
                        "chat_id",
                        ""
                    )
                    or ""
                ).strip(),

            "thread_id":
                str(
                    getattr(
                        source,
                        "thread_id",
                        ""
                    )
                    or ""
                ).strip(),

            "session_id": "",
        }

    def is_authorized(
        self,
        identity: Dict[str, str]
    ) -> bool:
        return (
            identity.get(
                "platform"
            ) == "telegram"
            and
            identity.get(
                "user_id"
            ) in self.authorized_ids()
        )

    # =====================================================
    # Candidate storage
    # =====================================================

    def load_candidates(
        self
    ) -> Dict[str, Dict[str, Any]]:
        raw = self.ctx.state.get(
            STATE_KEY,
            {}
        )

        candidates = (
            dict(raw)
            if isinstance(
                raw,
                dict
            )
            else {}
        )

        now = time.time()
        cleaned = {}

        for pending_id, candidate in candidates.items():
            if not isinstance(
                candidate,
                dict
            ):
                continue

            created_at = float(
                candidate.get(
                    "created_at"
                )
                or 0
            )

            if (
                created_at
                and
                now - created_at
                > CANDIDATE_TTL_SECONDS
            ):
                continue

            if (
                wa.get_pending(
                    wa.SKILLS,
                    str(pending_id)
                )
                is None
            ):
                continue

            cleaned[
                str(pending_id)
            ] = candidate

        if cleaned != candidates:
            self.ctx.state.set(
                STATE_KEY,
                cleaned
            )

        return cleaned

    def save_candidate(
        self,
        pending_id: str,
        identity: Dict[str, str],
        record: Dict[str, Any]
    ) -> None:
        payload = (
            record.get(
                "payload"
            )
            or {}
        )

        candidates = self.load_candidates()

        candidates[
            pending_id
        ] = {
            "pending_id":
                pending_id,

            "platform":
                identity.get(
                    "platform",
                    ""
                ),

            "user_id":
                identity.get(
                    "user_id",
                    ""
                ),

            "chat_id":
                identity.get(
                    "chat_id",
                    ""
                ),

            "thread_id":
                identity.get(
                    "thread_id",
                    ""
                ),

            "session_id":
                identity.get(
                    "session_id",
                    ""
                ),

            "skill_name":
                self.payload_skill_name(
                    payload
                ),

            "gist":
                str(
                    record.get(
                        "summary"
                    )
                    or ""
                ).strip(),

            "content":
                self.saved_content(
                    record
                ),

            "created_at":
                time.time(),
        }

        self.ctx.state.set(
            STATE_KEY,
            candidates
        )

    def remove_candidate(
        self,
        pending_id: str
    ) -> None:
        candidates = self.load_candidates()

        if pending_id in candidates:
            candidates.pop(
                pending_id,
                None
            )

            self.ctx.state.set(
                STATE_KEY,
                candidates
            )

    def matching_candidates(
        self,
        identity: Dict[str, str]
    ):
        result = []

        for candidate in self.load_candidates().values():
            if (
                candidate.get(
                    "platform"
                )
                != identity.get(
                    "platform"
                )
            ):
                continue

            if (
                candidate.get(
                    "user_id"
                )
                != identity.get(
                    "user_id"
                )
            ):
                continue

            if (
                candidate.get(
                    "chat_id"
                )
                != identity.get(
                    "chat_id"
                )
            ):
                continue

            if (
                str(
                    candidate.get(
                        "thread_id"
                    )
                    or ""
                )
                !=
                str(
                    identity.get(
                        "thread_id"
                    )
                    or ""
                )
            ):
                continue

            result.append(
                candidate
            )

        result.sort(
            key=lambda item:
                float(
                    item.get(
                        "created_at"
                    )
                    or 0
                ),
            reverse=True
        )

        return result

    # =====================================================
    # Natural text preapproval
    # =====================================================

    def route_key(
        self,
        identity: Dict[str, str]
    ) -> str:
        return "|".join(
            [
                identity.get(
                    "platform",
                    ""
                ),
                identity.get(
                    "user_id",
                    ""
                ),
                identity.get(
                    "chat_id",
                    ""
                ),
                identity.get(
                    "thread_id",
                    ""
                ),
            ]
        )

    def load_preapprovals(
        self
    ) -> Dict[str, float]:
        raw = self.ctx.state.get(
            PREAPPROVAL_KEY,
            {}
        )

        data = (
            dict(raw)
            if isinstance(
                raw,
                dict
            )
            else {}
        )

        now = time.time()
        cleaned = {}

        for key, value in data.items():
            try:
                stamped = float(
                    value
                )
            except Exception:
                continue

            if (
                now - stamped
                <= PREAPPROVAL_TTL_SECONDS
            ):
                cleaned[
                    str(key)
                ] = stamped

        if cleaned != data:
            self.ctx.state.set(
                PREAPPROVAL_KEY,
                cleaned
            )

        return cleaned

    def set_preapproval(
        self,
        identity: Dict[str, str]
    ) -> None:
        data = self.load_preapprovals()

        data[
            self.route_key(
                identity
            )
        ] = time.time()

        self.ctx.state.set(
            PREAPPROVAL_KEY,
            data
        )

    def consume_preapproval(
        self,
        identity: Dict[str, str]
    ) -> bool:
        data = self.load_preapprovals()

        key = self.route_key(
            identity
        )

        stamped = data.get(
            key
        )

        if not stamped:
            return False

        data.pop(
            key,
            None
        )

        self.ctx.state.set(
            PREAPPROVAL_KEY,
            data
        )

        return (
            time.time()
            - float(stamped)
            <= PREAPPROVAL_TTL_SECONDS
        )

    # =====================================================
    # Skill payload helpers
    # =====================================================

    def payload_skill_name(
        self,
        payload: Dict[str, Any]
    ) -> str:
        if (
            payload.get(
                "action"
            ) == "batch"
        ):
            operations = (
                payload.get(
                    "operations"
                )
                or []
            )

            names = []

            for operation in operations:
                if not isinstance(
                    operation,
                    dict
                ):
                    continue

                name = str(
                    operation.get(
                        "name"
                    )
                    or ""
                ).strip()

                if (
                    name
                    and
                    name not in names
                ):
                    names.append(
                        name
                    )

            return ", ".join(
                names
            )

        return str(
            payload.get(
                "name"
            )
            or ""
        ).strip()

    def saved_content(
        self,
        record: Dict[str, Any],
        max_chars: int = 2400
    ) -> str:
        payload = (
            record.get(
                "payload"
            )
            or {}
        )

        action = str(
            payload.get(
                "action"
            )
            or ""
        )

        if action == "batch":
            text = json.dumps(
                payload.get(
                    "operations"
                )
                or [],
                ensure_ascii=False,
                indent=2
            )

        elif action == "patch":
            text = (
                payload.get(
                    "new_string"
                )
                or
                payload.get(
                    "content"
                )
                or ""
            )

        elif action == "write_file":
            text = (
                payload.get(
                    "file_content"
                )
                or ""
            )

        else:
            text = (
                payload.get(
                    "content"
                )
                or ""
            )

        text = str(
            text
        ).strip()

        if len(text) > max_chars:
            text = (
                text[:max_chars]
                .rstrip()
                + "\n…"
            )

        return text

    # =====================================================
    # Pre-validation BEFORE human approval
    # =====================================================

    def preflight_operation(
        self,
        operation: Dict[str, Any]
    ) -> str:
        from tools.skill_manager_tool import (
            _find_skill,
            _validate_category,
            _validate_content_size,
            _validate_frontmatter,
            _validate_name,
        )

        action = str(
            operation.get(
                "action"
            )
            or ""
        ).strip()

        name = str(
            operation.get(
                "name"
            )
            or ""
        ).strip()

        if action == "create":
            error = _validate_name(
                name
            )

            if error:
                return error

            error = _validate_category(
                operation.get(
                    "category"
                )
            )

            if error:
                return error

            content = str(
                operation.get(
                    "content"
                )
                or ""
            )

            error = _validate_frontmatter(
                content,
                new_skill=True
            )

            if error:
                return error

            error = _validate_content_size(
                content
            )

            if error:
                return error

            if _find_skill(
                name
            ):
                return (
                    f"Skill '{name}' already exists. "
                    "Use patch/edit instead of create."
                )

        elif action in {
            "edit",
            "patch"
        }:
            content = operation.get(
                "content"
            )

            if content:
                content = str(
                    content
                )

                error = _validate_frontmatter(
                    content
                )

                if error:
                    return error

                error = _validate_content_size(
                    content
                )

                if error:
                    return error

        return ""

    def preflight_payload(
        self,
        payload: Dict[str, Any]
    ) -> str:
        if (
            payload.get(
                "action"
            ) == "batch"
        ):
            operations = (
                payload.get(
                    "operations"
                )
                or []
            )

            if not isinstance(
                operations,
                list
            ):
                return "Batch operations must be a list."

            for index, operation in enumerate(
                operations
            ):
                if not isinstance(
                    operation,
                    dict
                ):
                    return (
                        f"operations[{index}] "
                        "must be an object."
                    )

                error = self.preflight_operation(
                    operation
                )

                if error:
                    return (
                        f"operations[{index}]: "
                        f"{error}"
                    )

            return ""

        return self.preflight_operation(
            payload
        )

    # =====================================================
    # Apply / cancel
    # =====================================================

    def apply_pending(
        self,
        pending_id: str
    ) -> Dict[str, Any]:
        record = wa.get_pending(
            wa.SKILLS,
            pending_id
        )

        if record is None:
            self.remove_candidate(
                pending_id
            )

            return {
                "success": False,
                "saved": False,
                "error":
                    "pending_skill_not_found",
                "message":
                    "Pengajuan skill sudah tidak tersedia.",
            }

        payload = (
            record.get(
                "payload"
            )
            or {}
        )

        raw_result = apply_skill_pending(
            payload
        )

        result = _json_result(
            raw_result
        )

        if not result.get(
            "success"
        ):
            wa.discard_pending(
                wa.SKILLS,
                pending_id
            )

            self.remove_candidate(
                pending_id
            )

            return {
                "success": False,
                "saved": False,
                "error":
                    result.get(
                        "error"
                    )
                    or
                    "skill_write_failed",
                "message":
                    result.get(
                        "message"
                    )
                    or
                    "Skill gagal disimpan.",
            }

        wa.discard_pending(
            wa.SKILLS,
            pending_id
        )

        self.remove_candidate(
            pending_id
        )

        return {
            "success": True,
            "saved": True,

            "skill_name":
                self.payload_skill_name(
                    payload
                ),

            "saved_content":
                self.saved_content(
                    record
                ),

            "gist":
                str(
                    record.get(
                        "summary"
                    )
                    or ""
                ).strip(),

            "message":
                "Skill berhasil disimpan.",
        }

    def cancel_pending(
        self,
        pending_id: str
    ) -> Dict[str, Any]:
        record = wa.get_pending(
            wa.SKILLS,
            pending_id
        )

        skill_name = ""

        if record:
            payload = (
                record.get(
                    "payload"
                )
                or {}
            )

            skill_name = self.payload_skill_name(
                payload
            )

        wa.discard_pending(
            wa.SKILLS,
            pending_id
        )

        self.remove_candidate(
            pending_id
        )

        return {
            "success": True,
            "saved": False,
            "cancelled": True,
            "skill_name":
                skill_name,
        }

    # =====================================================
    # Native Telegram buttons
    # =====================================================

    def wire_telegram(
        self,
        application,
        adapter
    ):
        from telegram.ext import (
            CallbackQueryHandler,
        )

        self.telegram_application = application

        try:
            self.telegram_loop = (
                asyncio.get_running_loop()
            )
        except RuntimeError:
            self.telegram_loop = None

        async def on_button(
            update,
            context
        ):
            await self.handle_telegram_button(
                update
            )

        application.add_handler(
            CallbackQueryHandler(
                on_button,
                pattern=(
                    r"^ardiles_skill:"
                    r"(approve|cancel):"
                    r"[A-Za-z0-9_-]+$"
                )
            )
        )

    async def run_on_telegram_loop(
        self,
        coroutine
    ):
        if (
            self.telegram_loop is None
            or
            self.telegram_loop.is_closed()
        ):
            raise RuntimeError(
                "Telegram gateway loop is not available."
            )

        current_loop = asyncio.get_running_loop()

        if current_loop is self.telegram_loop:
            return await coroutine

        future = asyncio.run_coroutine_threadsafe(
            coroutine,
            self.telegram_loop
        )

        return await asyncio.wrap_future(
            future
        )

    async def request_skill_approval(
        self,
        args,
        **kwargs
    ):
        pending_id = str(
            args.get(
                "pending_id"
            )
            or ""
        ).strip()

        if not pending_id:
            return json.dumps(
                {
                    "success": False,
                    "error":
                        "pending_id_required",
                },
                ensure_ascii=False
            )

        identity = self.session_identity()

        if not self.is_authorized(
            identity
        ):
            return json.dumps(
                {
                    "success": False,
                    "error":
                        "skill_update_not_authorized",
                    "message":
                        "Telegram user ini tidak memiliki hak update skill.",
                },
                ensure_ascii=False
            )

        candidate = (
            self.load_candidates()
            .get(
                pending_id
            )
        )

        if not candidate:
            return json.dumps(
                {
                    "success": False,
                    "error":
                        "skill_candidate_not_found",
                },
                ensure_ascii=False
            )

        if (
            candidate.get(
                "user_id"
            )
            != identity.get(
                "user_id"
            )
            or
            candidate.get(
                "chat_id"
            )
            != identity.get(
                "chat_id"
            )
        ):
            return json.dumps(
                {
                    "success": False,
                    "error":
                        "skill_candidate_owner_mismatch",
                },
                ensure_ascii=False
            )

        record = wa.get_pending(
            wa.SKILLS,
            pending_id
        )

        if record is None:
            self.remove_candidate(
                pending_id
            )

            return json.dumps(
                {
                    "success": False,
                    "error":
                        "pending_skill_not_found",
                },
                ensure_ascii=False
            )

        validation_error = (
            self.preflight_payload(
                record.get(
                    "payload"
                )
                or {}
            )
        )

        if validation_error:
            wa.discard_pending(
                wa.SKILLS,
                pending_id
            )

            self.remove_candidate(
                pending_id
            )

            return json.dumps(
                {
                    "success": False,
                    "saved": False,
                    "error":
                        "skill_preflight_failed",
                    "validation_error":
                        validation_error,
                    "message": (
                        "Perbaiki skill terlebih dahulu. "
                        "Jangan minta approval user."
                    ),
                },
                ensure_ascii=False
            )

        if self.telegram_application is None:
            return json.dumps(
                {
                    "success": False,
                    "error":
                        "telegram_application_unavailable",
                },
                ensure_ascii=False
            )

        from telegram import (
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        skill_name = (
            candidate.get(
                "skill_name"
            )
            or "-"
        )

        content = (
            candidate.get(
                "content"
            )
            or
            candidate.get(
                "gist"
            )
            or "-"
        )

        preview = str(
            content
        )

        if len(preview) > 1800:
            preview = (
                preview[:1800]
                .rstrip()
                + "\n…"
            )

        text = (
            "🧠 Learning siap disimpan\n\n"
            f"Nama skill: {skill_name}\n\n"
            "Isi / perubahan:\n"
            f"{preview}\n\n"
            "Simpan learning ini?"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Update Skill",
                        callback_data=(
                            "ardiles_skill:"
                            f"approve:{pending_id}"
                        ),
                    ),
                    InlineKeyboardButton(
                        "❌ Batal",
                        callback_data=(
                            "ardiles_skill:"
                            f"cancel:{pending_id}"
                        ),
                    ),
                ]
            ]
        )

        send_kwargs = {
            "chat_id":
                identity.get(
                    "chat_id"
                ),
            "text":
                text,
            "reply_markup":
                keyboard,
        }

        thread_id = str(
            identity.get(
                "thread_id"
            )
            or ""
        ).strip()

        if thread_id.isdigit():
            send_kwargs[
                "message_thread_id"
            ] = int(
                thread_id
            )

        await self.run_on_telegram_loop(
            self.telegram_application
            .bot
            .send_message(
                **send_kwargs
            )
        )

        return json.dumps(
            {
                "success": True,
                "saved": False,
                "awaiting_human_approval": True,
                "pending_id":
                    pending_id,
                "skill_name":
                    skill_name,
                "message": (
                    "Native Telegram approval buttons sent. "
                    "Do not call clarify. "
                    "Do not claim the skill is saved yet."
                ),
            },
            ensure_ascii=False
        )

    async def handle_telegram_button(
        self,
        update
    ):
        query = getattr(
            update,
            "callback_query",
            None
        )

        if query is None:
            return

        data = str(
            query.data
            or ""
        )

        parts = data.split(
            ":",
            2
        )

        if len(parts) != 3:
            return

        _prefix = parts[0]
        action = parts[1]
        pending_id = parts[2]

        user = getattr(
            update,
            "effective_user",
            None
        )

        chat = getattr(
            update,
            "effective_chat",
            None
        )

        user_id = str(
            getattr(
                user,
                "id",
                ""
            )
            or ""
        )

        chat_id = str(
            getattr(
                chat,
                "id",
                ""
            )
            or ""
        )

        if (
            user_id
            not in self.authorized_ids()
        ):
            await query.answer(
                "Anda tidak memiliki hak update skill.",
                show_alert=True
            )
            return

        candidate = (
            self.load_candidates()
            .get(
                pending_id
            )
        )

        if not candidate:
            await query.answer(
                "Pengajuan ini sudah tidak tersedia.",
                show_alert=True
            )
            return

        if (
            candidate.get(
                "user_id"
            ) != user_id
            or
            candidate.get(
                "chat_id"
            ) != chat_id
        ):
            await query.answer(
                "Approval ini bukan milik user/chat ini.",
                show_alert=True
            )
            return

        await query.answer()

        if action == "cancel":
            result = self.cancel_pending(
                pending_id
            )

            message = (
                "❌ Update skill dibatalkan\n\n"
                "Nama skill: "
                f"{result.get('skill_name') or '-'}"
            )

            await self.edit_or_reply(
                query,
                message
            )

            return

        if action != "approve":
            return

        result = self.apply_pending(
            pending_id
        )

        if not result.get(
            "saved"
        ):
            message = (
                "⚠️ Skill belum tersimpan\n\n"
                "Alasan:\n"
                f"{result.get('message') or result.get('error') or 'Unknown error'}"
            )

            await self.edit_or_reply(
                query,
                message
            )

            return

        skill_name = (
            result.get(
                "skill_name"
            )
            or "-"
        )

        saved_content = (
            result.get(
                "saved_content"
            )
            or
            result.get(
                "gist"
            )
            or "-"
        )

        if len(saved_content) > 2800:
            saved_content = (
                saved_content[:2800]
                .rstrip()
                + "\n…"
            )

        message = (
            "✅ Skill berhasil disimpan\n\n"
            f"Nama skill: {skill_name}\n\n"
            "Isi yang disimpan:\n"
            f"{saved_content}"
        )

        await self.edit_or_reply(
            query,
            message
        )

    async def edit_or_reply(
        self,
        query,
        text: str
    ):
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=None
            )

        except Exception:
            message = getattr(
                query,
                "message",
                None
            )

            if message is not None:
                await message.reply_text(
                    text
                )

    # =====================================================
    # Gateway text fallback
    # =====================================================

    def pre_gateway_dispatch(
        self,
        event,
        **kwargs
    ):
        identity = self.event_identity(
            event
        )

        raw_text = str(
            getattr(
                event,
                "text",
                ""
            )
            or ""
        ).strip()

        normalized = _normalize_text(
            raw_text
        )

        # Block native /skills commands
        # from unauthorized Telegram users.
        if re.match(
            r"^/skills(?:@\w+)?(?:\s|$)",
            raw_text,
            re.I
        ):
            if (
                identity.get(
                    "platform"
                ) == "telegram"
                and
                not self.is_authorized(
                    identity
                )
            ):
                return {
                    "action": "rewrite",
                    "text": (
                        "Permintaan perubahan skill ditolak. "
                        "Telegram user ini tidak memiliki "
                        "hak update skill bersama."
                    ),
                }

            return None

        if normalized not in TRIGGERS:
            return None

        if not self.is_authorized(
            identity
        ):
            return {
                "action": "rewrite",
                "text": (
                    "Permintaan update skill ditolak. "
                    "Telegram user ini tidak memiliki "
                    "hak update skill bersama. "
                    "Jangan memanggil skill_manage."
                ),
            }

        candidates = self.matching_candidates(
            identity
        )

        if len(candidates) == 1:
            result = self.apply_pending(
                candidates[0][
                    "pending_id"
                ]
            )

            return {
                "action": "rewrite",
                "text": (
                    "[ARDILES VERIFIED SKILL APPROVAL]\n"
                    + json.dumps(
                        result,
                        ensure_ascii=False
                    )
                    + "\nJika saved=true, konfirmasi "
                    "nama skill dan isi yang disimpan. "
                    "Jangan panggil skill_manage lagi."
                ),
            }

        if len(candidates) > 1:
            return {
                "action": "rewrite",
                "text": (
                    "Ada lebih dari satu pengajuan skill "
                    "yang belum selesai. "
                    "Jangan menyimpan apa pun. "
                    "Minta user menentukan skill yang dimaksud."
                ),
            }

        self.set_preapproval(
            identity
        )

        return {
            "action": "rewrite",
            "text": (
                "[ARDILES VERIFIED SKILL PRE-APPROVAL]\n"
                "User Telegram yang diotorisasi telah "
                "memberi approval eksplisit dengan "
                "trigger update skill/simpan skill. "
                "Buat atau update learning yang relevan "
                "dengan skill_manage. "
                "Jika valid, policy akan langsung "
                "menyimpannya tanpa approval kedua. "
                "Setelah sukses WAJIB konfirmasi "
                "nama skill dan isi yang disimpan."
            ),
        }

    # =====================================================
    # LLM instructions
    # =====================================================

    def pre_llm_call(
        self,
        session_id="",
        user_message="",
        platform="",
        sender_id="",
        **kwargs
    ):
        identity = self.session_identity()

        if platform:
            identity[
                "platform"
            ] = _platform_name(
                platform
            )

        if sender_id:
            identity[
                "user_id"
            ] = str(
                sender_id
            ).strip()

        if not self.is_authorized(
            identity
        ):
            return None

        return {
            "context": (
                "ARDILES SKILL APPROVAL POLICY:\n"
                "- Untuk approval skill Ardiles JANGAN gunakan clarify.\n"
                "- Gunakan skill_manage untuk menyiapkan perubahan.\n"
                "- Jika hasil skill_manage berisi "
                "skill_preflight_failed, perbaiki payload skill "
                "dan panggil skill_manage lagi SEBELUM meminta "
                "approval manusia.\n"
                "- Jika hasil skill_manage berisi "
                "ready_for_human_approval=true, segera panggil "
                "request_skill_approval dengan pending_id tersebut.\n"
                "- request_skill_approval akan mengirim tombol native "
                "Telegram: Update Skill dan Batal.\n"
                "- Jangan mengatakan skill sudah tersimpan ketika "
                "awaiting_human_approval=true.\n"
                "- Jika user menulis persis 'update skill' atau "
                "'simpan skill', itu adalah approval eksplisit.\n"
                "- Setelah skill benar-benar berhasil disimpan, "
                "WAJIB konfirmasi nama skill dan isi/rule/framework "
                "yang disimpan."
            )
        }

    # =====================================================
    # Tool result interception
    # =====================================================

    def transform_tool_result(
        self,
        tool_name,
        args,
        result,
        session_id="",
        turn_id="",
        **kwargs
    ):
        if tool_name != "skill_manage":
            return None

        parsed = _json_result(
            result
        )

        if (
            not parsed.get(
                "staged"
            )
            or
            not parsed.get(
                "pending_id"
            )
        ):
            return None

        pending_id = str(
            parsed.get(
                "pending_id"
            )
        )

        identity = self.session_identity()

        if session_id:
            identity[
                "session_id"
            ] = str(
                session_id
            )

        # No skill write outside authorized Telegram users.
        if not self.is_authorized(
            identity
        ):
            wa.discard_pending(
                wa.SKILLS,
                pending_id
            )

            self.remove_candidate(
                pending_id
            )

            return json.dumps(
                {
                    "success": False,
                    "saved": False,
                    "error":
                        "skill_update_not_authorized",
                    "message":
                        "Skill tidak disimpan. User tidak berwenang.",
                },
                ensure_ascii=False
            )

        record = wa.get_pending(
            wa.SKILLS,
            pending_id
        )

        if record is None:
            return json.dumps(
                {
                    "success": False,
                    "saved": False,
                    "error":
                        "pending_skill_not_found",
                },
                ensure_ascii=False
            )

        # IMPORTANT:
        # validate BEFORE showing human approval.
        validation_error = (
            self.preflight_payload(
                record.get(
                    "payload"
                )
                or {}
            )
        )

        if validation_error:
            wa.discard_pending(
                wa.SKILLS,
                pending_id
            )

            self.remove_candidate(
                pending_id
            )

            return json.dumps(
                {
                    "success": False,
                    "saved": False,
                    "error":
                        "skill_preflight_failed",
                    "validation_error":
                        validation_error,
                    "message": (
                        "Payload skill belum valid. "
                        "Perbaiki sekarang dan panggil "
                        "skill_manage lagi. "
                        "JANGAN meminta approval user "
                        "sebelum valid."
                    ),
                },
                ensure_ascii=False
            )

        self.save_candidate(
            pending_id,
            identity,
            record
        )

        # Text trigger already approved this write.
        if self.consume_preapproval(
            identity
        ):
            return json.dumps(
                self.apply_pending(
                    pending_id
                ),
                ensure_ascii=False
            )

        return json.dumps(
            {
                "success": True,
                "saved": False,
                "staged": True,
                "ready_for_human_approval": True,
                "pending_id":
                    pending_id,
                "skill_name":
                    self.payload_skill_name(
                        record.get(
                            "payload"
                        )
                        or {}
                    ),
                "message": (
                    "Skill sudah lolos pre-validation. "
                    "Sekarang panggil request_skill_approval "
                    "dengan pending_id ini. "
                    "JANGAN gunakan clarify."
                ),
            },
            ensure_ascii=False
        )
