import asyncio
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict

from gateway.session_context import get_session_env
from hermes_constants import (
    reset_hermes_home_override,
    set_hermes_home_override,
)
from tools import write_approval as wa
from tools.skill_manager_tool import apply_skill_pending


# =========================================================
# ARDILES SECURE SKILL APPROVAL
#
# Authorized Telegram users only.
#
# Natural commands:
#   update skill
#   simpan skill
#   pending skill
#   pending skills
#   skill pending
#
# Approval UI:
#   Native Telegram buttons.
#   DOES NOT use Hermes clarify.
# =========================================================


TRIGGERS = {
    "update skill",
    "simpan skill",
}

PENDING_TRIGGERS = {
    "pending skill",
    "pending skills",
    "skill pending",
}

STATE_KEY = "skill_update_candidates"
PREAPPROVAL_KEY = "skill_update_preapprovals"

PREAPPROVAL_TTL_SECONDS = 180
CANDIDATE_TTL_SECONDS = 7 * 24 * 60 * 60


REQUEST_SKILL_APPROVAL = {
    "name": "request_skill_approval",
    "description": (
        "Show native Telegram Update Skill / Batal buttons for one "
        "validated staged Ardiles skill write. Call this only after "
        "skill_manage returns ready_for_human_approval=true. "
        "Never use clarify for Ardiles skill approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pending_id": {
                "type": "string",
                "description": (
                    "The pending_id returned by skill_manage after "
                    "the Ardiles pre-validation succeeds."
                ),
            },
        },
        "required": [
            "pending_id"
        ],
    },
}


# =========================================================
# HELPERS
# =========================================================


def _normalize_text(
    value: Any
) -> str:
    return " ".join(
        str(
            value
            or ""
        )
        .strip()
        .lower()
        .split()
    )


def _platform_name(
    value: Any
) -> str:
    raw = getattr(
        value,
        "value",
        value,
    )

    return str(
        raw
        or ""
    ).strip().lower()


def _json_result(
    value: Any
) -> Dict[str, Any]:
    if isinstance(
        value,
        dict
    ):
        return dict(
            value
        )

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


def _error_text(
    value: Any
) -> str:
    parsed = _json_result(
        value
    )

    if parsed:
        return str(
            parsed.get(
                "error"
            )
            or
            parsed.get(
                "message"
            )
            or value
        )

    return str(
        value
        or ""
    )


# =========================================================
# MAIN CLASS
# =========================================================


class SkillApproval:
    def __init__(
        self,
        ctx
    ):
        self.ctx = ctx

        # Capture the profile home WHILE plugin registration
        # is running inside the correct routed profile.
        #
        # ctx.state.data_dir:
        #   <PROFILE_HOME>/plugin-data/<plugin-namespace>
        self.profile_home = Path(
            ctx.state.data_dir
        ).parent.parent.resolve()

        self.telegram_application = None
        self.telegram_loop = None

    # =====================================================
    # PROFILE SCOPE
    #
    # Native Telegram callback handlers do not necessarily
    # inherit the active ardiles-stock HERMES_HOME.
    #
    # Every pending/state operation is therefore explicitly
    # scoped back to this plugin's profile.
    # =====================================================

    @contextmanager
    def profile_scope(
        self
    ):
        token = set_hermes_home_override(
            str(
                self.profile_home
            )
        )

        try:
            yield

        finally:
            reset_hermes_home_override(
                token
            )

    # =====================================================
    # AUTHORIZATION
    # =====================================================

    def authorized_ids(
        self
    ) -> set[str]:
        with self.profile_scope():
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
                str(
                    raw
                    or ""
                )
            )

        return {
            str(
                item
            ).strip()
            for item in parts
            if str(
                item
            ).strip().isdigit()
        }

    def is_authorized_user_id(
        self,
        user_id: Any
    ) -> bool:
        return (
            str(
                user_id
                or ""
            ).strip()
            in self.authorized_ids()
        )

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
    # CANDIDATE STORAGE
    # =====================================================

    def load_candidates(
        self
    ) -> Dict[str, Dict[str, Any]]:
        with self.profile_scope():
            raw = self.ctx.state.get(
                STATE_KEY,
                {}
            )

            candidates = (
                dict(
                    raw
                )
                if isinstance(
                    raw,
                    dict
                )
                else {}
            )

            now = time.time()
            cleaned = {}

            for (
                pending_id,
                candidate
            ) in candidates.items():

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
                        str(
                            pending_id
                        )
                    )
                    is None
                ):
                    continue

                cleaned[
                    str(
                        pending_id
                    )
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

        with self.profile_scope():
            self.ctx.state.set(
                STATE_KEY,
                candidates
            )

    def remove_candidate(
        self,
        pending_id: str
    ) -> None:
        candidates = self.load_candidates()

        if pending_id not in candidates:
            return

        candidates.pop(
            pending_id,
            None
        )

        with self.profile_scope():
            self.ctx.state.set(
                STATE_KEY,
                candidates
            )

    def matching_candidates(
        self,
        identity: Dict[str, str]
    ):
        result = []

        for candidate in (
            self.load_candidates()
            .values()
        ):
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
    # PREAPPROVAL
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
        with self.profile_scope():
            raw = self.ctx.state.get(
                PREAPPROVAL_KEY,
                {}
            )

            data = (
                dict(
                    raw
                )
                if isinstance(
                    raw,
                    dict
                )
                else {}
            )

            now = time.time()
            cleaned = {}

            for (
                key,
                value
            ) in data.items():

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
                        str(
                            key
                        )
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

        with self.profile_scope():
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

        with self.profile_scope():
            self.ctx.state.set(
                PREAPPROVAL_KEY,
                data
            )

        return (
            time.time()
            - float(
                stamped
            )
            <= PREAPPROVAL_TTL_SECONDS
        )

    # =====================================================
    # PENDING RECORD HELPERS
    # =====================================================

    def get_pending(
        self,
        pending_id: str
    ):
        with self.profile_scope():
            return wa.get_pending(
                wa.SKILLS,
                pending_id
            )

    def list_pending(
        self
    ):
        with self.profile_scope():
            return wa.list_pending(
                wa.SKILLS
            )

    def discard_pending(
        self,
        pending_id: str
    ) -> bool:
        with self.profile_scope():
            return wa.discard_pending(
                wa.SKILLS,
                pending_id
            )

    # =====================================================
    # SKILL PAYLOAD
    # =====================================================

    def payload_skill_names(
        self,
        payload: Dict[str, Any]
    ):
        names = []

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

        else:
            name = str(
                payload.get(
                    "name"
                )
                or ""
            ).strip()

            if name:
                names.append(
                    name
                )

        return names

    def payload_skill_name(
        self,
        payload: Dict[str, Any]
    ) -> str:
        names = self.payload_skill_names(
            payload
        )

        return ", ".join(
            names
        )

    def payload_operations_text(
        self,
        payload: Dict[str, Any]
    ) -> str:
        if (
            payload.get(
                "action"
            ) != "batch"
        ):
            action = str(
                payload.get(
                    "action"
                )
                or "-"
            )

            name = str(
                payload.get(
                    "name"
                )
                or "-"
            )

            return (
                f"{action} — {name}"
            )

        operations = (
            payload.get(
                "operations"
            )
            or []
        )

        lines = []

        for (
            index,
            operation
        ) in enumerate(
            operations,
            start=1
        ):
            if not isinstance(
                operation,
                dict
            ):
                continue

            action = str(
                operation.get(
                    "action"
                )
                or "-"
            )

            name = str(
                operation.get(
                    "name"
                )
                or "-"
            )

            file_path = str(
                operation.get(
                    "file_path"
                )
                or ""
            ).strip()

            line = (
                f"{index}. {action} — {name}"
            )

            if file_path:
                line += (
                    f" — {file_path}"
                )

            lines.append(
                line
            )

        return (
            "\n".join(
                lines
            )
            or "-"
        )

    def saved_content(
        self,
        record: Dict[str, Any],
        max_chars: int = 2600
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

        texts = []

        if action == "batch":
            operations = (
                payload.get(
                    "operations"
                )
                or []
            )

            for operation in operations:
                if not isinstance(
                    operation,
                    dict
                ):
                    continue

                op_action = str(
                    operation.get(
                        "action"
                    )
                    or ""
                )

                name = str(
                    operation.get(
                        "name"
                    )
                    or ""
                )

                if op_action in {
                    "create",
                    "edit"
                }:
                    content = str(
                        operation.get(
                            "content"
                        )
                        or ""
                    ).strip()

                    if content:
                        texts.append(
                            f"[{name}]\n{content}"
                        )

                elif op_action == "patch":
                    change = (
                        operation.get(
                            "new_string"
                        )
                        or
                        operation.get(
                            "content"
                        )
                        or ""
                    )

                    if change:
                        texts.append(
                            f"[{name}]\n{change}"
                        )

                elif op_action == "write_file":
                    file_content = str(
                        operation.get(
                            "file_content"
                        )
                        or ""
                    ).strip()

                    if file_content:
                        texts.append(
                            f"[{name} / "
                            f"{operation.get('file_path') or 'file'}]\n"
                            f"{file_content}"
                        )

        elif action in {
            "create",
            "edit"
        }:
            texts.append(
                str(
                    payload.get(
                        "content"
                    )
                    or ""
                )
            )

        elif action == "patch":
            texts.append(
                str(
                    payload.get(
                        "new_string"
                    )
                    or
                    payload.get(
                        "content"
                    )
                    or ""
                )
            )

        elif action == "write_file":
            texts.append(
                str(
                    payload.get(
                        "file_content"
                    )
                    or ""
                )
            )

        text = "\n\n".join(
            item.strip()
            for item in texts
            if str(
                item
            ).strip()
        )

        if not text:
            text = str(
                record.get(
                    "summary"
                )
                or ""
            )

        if len(
            text
        ) > max_chars:
            text = (
                text[
                    :max_chars
                ].rstrip()
                + "\n…"
            )

        return text

    # =====================================================
    # PREFLIGHT VALIDATION
    # =====================================================

    def preflight_operation(
        self,
        operation: Dict[str, Any],
        planned_creates=None
    ) -> str:
        from tools.skill_manager_batch import (
            _op_shape_error,
        )

        from tools.skill_manager_tool import (
            _find_skill,
            _validate_category,
            _validate_content_size,
            _validate_frontmatter,
            _validate_name,
        )

        planned_creates = (
            planned_creates
            or set()
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

        shape_error = _op_shape_error(
            action,
            operation
        )

        if shape_error:
            return str(
                shape_error
            )

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

            return ""

        # Operations after a create in the SAME batch
        # are allowed even though the skill is not yet
        # present on disk.
        existing = _find_skill(
            name
        )

        if (
            not existing
            and
            name not in planned_creates
        ):
            return (
                f"Skill '{name}' does not exist."
            )

        if action == "edit":
            content = str(
                operation.get(
                    "content"
                )
                or ""
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

        elif action == "patch":
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
        action = str(
            payload.get(
                "action"
            )
            or ""
        )

        if action != "batch":
            with self.profile_scope():
                return self.preflight_operation(
                    payload
                )

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
            return (
                "Batch operations must be a list."
            )

        if not operations:
            return (
                "Batch operations cannot be empty."
            )

        planned_creates = {
            str(
                operation.get(
                    "name"
                )
                or ""
            ).strip()
            for operation in operations
            if (
                isinstance(
                    operation,
                    dict
                )
                and
                operation.get(
                    "action"
                ) == "create"
            )
        }

        with self.profile_scope():
            for (
                index,
                operation
            ) in enumerate(
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
                    operation,
                    planned_creates=planned_creates
                )

                if error:
                    return (
                        f"operations[{index}]: "
                        f"{error}"
                    )

        return ""

    # =====================================================
    # APPLY / REJECT
    # =====================================================

    def apply_pending(
        self,
        pending_id: str
    ) -> Dict[str, Any]:
        record = self.get_pending(
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

        validation_error = (
            self.preflight_payload(
                payload
            )
        )

        if validation_error:
            return {
                "success": False,
                "saved": False,
                "error":
                    "skill_preflight_failed",
                "message":
                    validation_error,
            }

        with self.profile_scope():
            raw_result = apply_skill_pending(
                payload
            )

        result = _json_result(
            raw_result
        )

        if not result.get(
            "success"
        ):
            # Do NOT discard it.
            # An unexpected transient/runtime error
            # must not destroy the pending request.
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
                    _error_text(
                        raw_result
                    )
                    or
                    "Skill gagal disimpan.",
            }

        self.discard_pending(
            pending_id
        )

        self.remove_candidate(
            pending_id
        )

        return {
            "success": True,
            "saved": True,

            "pending_id":
                pending_id,

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

    def reject_pending(
        self,
        pending_id: str
    ) -> Dict[str, Any]:
        record = self.get_pending(
            pending_id
        )

        skill_name = ""

        if record:
            skill_name = (
                self.payload_skill_name(
                    record.get(
                        "payload"
                    )
                    or {}
                )
            )

        removed = self.discard_pending(
            pending_id
        )

        self.remove_candidate(
            pending_id
        )

        return {
            "success":
                bool(
                    removed
                ),

            "saved": False,

            "rejected":
                bool(
                    removed
                ),

            "skill_name":
                skill_name,

            "pending_id":
                pending_id,
        }

    # =====================================================
    # TELEGRAM WIRING
    # =====================================================

    def wire_telegram(
        self,
        application,
        adapter
    ):
        from telegram.ext import (
            CallbackQueryHandler,
            MessageHandler,
            filters,
        )

        self.telegram_application = application

        try:
            self.telegram_loop = (
                asyncio.get_running_loop()
            )

        except RuntimeError:
            self.telegram_loop = None

        # ---------------------------------------------
        # Native button callbacks
        # ---------------------------------------------

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
                pattern=r"^ardiles_skill:"
            )
        )

        # ---------------------------------------------
        # Native:
        #
        # pending skill
        #
        # This bypasses the LLM entirely.
        # ---------------------------------------------

        async def on_pending_skill(
            update,
            context
        ):
            await self.handle_pending_skill_command(
                update
            )

        application.add_handler(
            MessageHandler(
                filters.TEXT
                &
                filters.Regex(
                    re.compile(
                        r"^\s*"
                        r"(?:pending\s+skills?"
                        r"|skill\s+pending)"
                        r"\s*$",
                        re.IGNORECASE
                    )
                ),
                on_pending_skill
            )
        )

    # =====================================================
    # TELEGRAM LOOP BRIDGE
    # =====================================================

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

        current_loop = (
            asyncio.get_running_loop()
        )

        if (
            current_loop
            is self.telegram_loop
        ):
            return await coroutine

        future = (
            asyncio.run_coroutine_threadsafe(
                coroutine,
                self.telegram_loop
            )
        )

        return await asyncio.wrap_future(
            future
        )

    # =====================================================
    # DIRECT APPROVAL TOOL
    # =====================================================

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
                    "saved": False,
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
                    "saved": False,
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
                    "saved": False,
                    "error":
                        "skill_candidate_not_found",
                },
                ensure_ascii=False
            )

        # Direct approval card belongs to
        # the human/chat that generated it.
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
                    "saved": False,
                    "error":
                        "skill_candidate_owner_mismatch",
                },
                ensure_ascii=False
            )

        record = self.get_pending(
            pending_id
        )

        if record is None:
            self.remove_candidate(
                pending_id
            )

            return json.dumps(
                {
                    "success": False,
                    "saved": False,
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
            # Invalid payload never reaches
            # human approval.
            self.discard_pending(
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
                        "Perbaiki payload skill dahulu. "
                        "Jangan meminta approval user."
                    ),
                },
                ensure_ascii=False
            )

        await self.send_direct_approval_card(
            identity,
            record
        )

        return json.dumps(
            {
                "success": True,
                "saved": False,
                "awaiting_human_approval": True,
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
                    "Native Telegram buttons sent. "
                    "Do not call clarify. "
                    "Do not claim the skill is saved."
                ),
            },
            ensure_ascii=False
        )

    async def send_direct_approval_card(
        self,
        identity: Dict[str, str],
        record: Dict[str, Any]
    ):
        from telegram import (
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        pending_id = str(
            record.get(
                "id"
            )
            or ""
        )

        payload = (
            record.get(
                "payload"
            )
            or {}
        )

        skill_name = (
            self.payload_skill_name(
                payload
            )
            or "-"
        )

        preview = (
            self.saved_content(
                record,
                max_chars=1800
            )
            or
            str(
                record.get(
                    "summary"
                )
                or "-"
            )
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
                            "direct_approve:"
                            f"{pending_id}"
                        ),
                    ),

                    InlineKeyboardButton(
                        "❌ Batal",
                        callback_data=(
                            "ardiles_skill:"
                            "direct_cancel:"
                            f"{pending_id}"
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

    # =====================================================
    # PENDING SKILL MANAGEMENT
    # =====================================================

    async def handle_pending_skill_command(
        self,
        update
    ):
        user = getattr(
            update,
            "effective_user",
            None
        )

        message = getattr(
            update,
            "effective_message",
            None
        )

        if message is None:
            return

        user_id = str(
            getattr(
                user,
                "id",
                ""
            )
            or ""
        )

        if not self.is_authorized_user_id(
            user_id
        ):
            await message.reply_text(
                "⛔ Anda tidak memiliki hak "
                "untuk melihat atau menyetujui pending skill."
            )
            return

        await self.send_pending_page(
            message=message,
            page=0,
            edit=False
        )

    async def send_pending_page(
        self,
        *,
        message=None,
        query=None,
        page: int = 0,
        edit: bool = False
    ):
        from telegram import (
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        records = self.list_pending()

        if not records:
            text = (
                "✅ Tidak ada pending skill."
            )

            if (
                edit
                and
                query is not None
            ):
                try:
                    await query.edit_message_text(
                        text=text,
                        reply_markup=None
                    )

                except Exception:
                    if query.message:
                        await query.message.reply_text(
                            text
                        )

            elif message is not None:
                await message.reply_text(
                    text
                )

            return

        total = len(
            records
        )

        if page < 0:
            page = total - 1

        if page >= total:
            page = 0

        record = records[
            page
        ]

        pending_id = str(
            record.get(
                "id"
            )
            or ""
        )

        payload = (
            record.get(
                "payload"
            )
            or {}
        )

        skill_name = (
            self.payload_skill_name(
                payload
            )
            or "-"
        )

        summary = str(
            record.get(
                "summary"
            )
            or "-"
        )

        operations = (
            self.payload_operations_text(
                payload
            )
        )

        preview = (
            self.saved_content(
                record,
                max_chars=1200
            )
            or "-"
        )

        text = (
            "🧠 Pending Skill\n\n"
            f"{page + 1} dari {total}\n\n"
            f"ID: {pending_id}\n"
            f"Nama skill: {skill_name}\n\n"
            f"Ringkasan:\n{summary}\n\n"
            f"Operasi:\n{operations}\n\n"
            f"Isi / perubahan:\n{preview}"
        )

        rows = [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=(
                        "ardiles_skill:"
                        "review_approve:"
                        f"{pending_id}"
                    ),
                ),

                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=(
                        "ardiles_skill:"
                        "review_reject:"
                        f"{pending_id}"
                    ),
                ),
            ]
        ]

        if total > 1:
            previous_page = (
                page - 1
            ) % total

            next_page = (
                page + 1
            ) % total

            rows.append(
                [
                    InlineKeyboardButton(
                        "⬅️ Sebelumnya",
                        callback_data=(
                            "ardiles_skill:"
                            "review_page:"
                            f"{previous_page}"
                        ),
                    ),

                    InlineKeyboardButton(
                        "➡️ Berikutnya",
                        callback_data=(
                            "ardiles_skill:"
                            "review_page:"
                            f"{next_page}"
                        ),
                    ),
                ]
            )

        keyboard = InlineKeyboardMarkup(
            rows
        )

        if (
            edit
            and
            query is not None
        ):
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=keyboard
                )

            except Exception:
                if query.message:
                    await query.message.reply_text(
                        text=text,
                        reply_markup=keyboard
                    )

        elif message is not None:
            await message.reply_text(
                text=text,
                reply_markup=keyboard
            )

    # =====================================================
    # BUTTON HANDLER
    # =====================================================

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

        if len(
            parts
        ) != 3:
            return

        _prefix = parts[0]
        action = parts[1]
        value = parts[2]

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

        if not self.is_authorized_user_id(
            user_id
        ):
            await query.answer(
                "Anda tidak memiliki hak update skill.",
                show_alert=True
            )
            return

        # ---------------------------------------------
        # REVIEW PAGINATION
        # ---------------------------------------------

        if action == "review_page":
            await query.answer()

            try:
                page = int(
                    value
                )

            except Exception:
                page = 0

            await self.send_pending_page(
                query=query,
                page=page,
                edit=True
            )

            return

        pending_id = str(
            value
        ).strip()

        record = self.get_pending(
            pending_id
        )

        if record is None:
            await query.answer(
                "Pending ini sudah tidak tersedia.",
                show_alert=True
            )

            if action.startswith(
                "review_"
            ):
                await self.send_pending_page(
                    query=query,
                    page=0,
                    edit=True
                )

            return

        # ---------------------------------------------
        # DIRECT CARD
        #
        # Must belong to same human/chat.
        # ---------------------------------------------

        if action in {
            "direct_approve",
            "direct_cancel"
        }:
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

        # ---------------------------------------------
        # DIRECT CANCEL
        # ---------------------------------------------

        if action == "direct_cancel":
            result = self.reject_pending(
                pending_id
            )

            await self.edit_or_reply(
                query,
                (
                    "❌ Update skill dibatalkan\n\n"
                    "Nama skill: "
                    f"{result.get('skill_name') or '-'}"
                )
            )

            return

        # ---------------------------------------------
        # DIRECT APPROVE
        # ---------------------------------------------

        if action == "direct_approve":
            result = self.apply_pending(
                pending_id
            )

            await self.show_apply_result(
                query,
                result,
                show_next=False
            )

            return

        # ---------------------------------------------
        # REVIEW REJECT
        #
        # Boss/Andreas may reject ANY pending skill
        # from the Ardiles profile, including legacy
        # records that predate this plugin.
        # ---------------------------------------------

        if action == "review_reject":
            result = self.reject_pending(
                pending_id
            )

            remaining = self.list_pending()

            text = (
                "❌ Pending skill ditolak\n\n"
                f"Nama skill: "
                f"{result.get('skill_name') or '-'}\n"
                f"ID: {pending_id}"
            )

            await self.edit_after_review(
                query,
                text=text,
                has_next=bool(
                    remaining
                )
            )

            return

        # ---------------------------------------------
        # REVIEW APPROVE
        #
        # Boss/Andreas may approve legacy pending
        # entries too.
        # ---------------------------------------------

        if action == "review_approve":
            result = self.apply_pending(
                pending_id
            )

            await self.show_apply_result(
                query,
                result,
                show_next=True
            )

            return

    # =====================================================
    # RESULT UI
    # =====================================================

    async def show_apply_result(
        self,
        query,
        result: Dict[str, Any],
        *,
        show_next: bool
    ):
        if not result.get(
            "saved"
        ):
            text = (
                "⚠️ Skill belum tersimpan\n\n"
                "Alasan:\n"
                f"{result.get('message') "
                "or result.get('error') "
                "or 'Unknown error'}"
            )

            await self.edit_after_review(
                query,
                text=text,
                has_next=(
                    show_next
                    and
                    bool(
                        self.list_pending()
                    )
                )
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

        if len(
            saved_content
        ) > 2800:
            saved_content = (
                saved_content[
                    :2800
                ].rstrip()
                + "\n…"
            )

        text = (
            "✅ Skill berhasil disimpan\n\n"
            f"Nama skill: {skill_name}\n\n"
            "Isi yang disimpan:\n"
            f"{saved_content}"
        )

        await self.edit_after_review(
            query,
            text=text,
            has_next=(
                show_next
                and
                bool(
                    self.list_pending()
                )
            )
        )

    async def edit_after_review(
        self,
        query,
        *,
        text: str,
        has_next: bool
    ):
        from telegram import (
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        keyboard = None

        if has_next:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "➡️ Pending Berikutnya",
                            callback_data=(
                                "ardiles_skill:"
                                "review_page:0"
                            ),
                        )
                    ]
                ]
            )

        try:
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard
            )

        except Exception:
            message = getattr(
                query,
                "message",
                None
            )

            if message is not None:
                await message.reply_text(
                    text=text,
                    reply_markup=keyboard
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
    # NATURAL TEXT FALLBACK
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

        # ---------------------------------------------
        # Protect native Hermes /skills commands.
        # ---------------------------------------------

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

        # pending skill is intercepted by the
        # native Telegram MessageHandler.
        if normalized in PENDING_TRIGGERS:
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

        # ---------------------------------------------
        # One staged candidate:
        # typed "update skill" = approval.
        # ---------------------------------------------

        if len(
            candidates
        ) == 1:
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
                    + "\nJika saved=true, WAJIB konfirmasi "
                    "nama skill dan isi yang disimpan. "
                    "Jangan panggil skill_manage lagi."
                ),
            }

        if len(
            candidates
        ) > 1:
            return {
                "action": "rewrite",
                "text": (
                    "Ada lebih dari satu pengajuan skill "
                    "untuk percakapan ini. "
                    "Jangan menyimpan apa pun. "
                    "Minta user menggunakan 'pending skill' "
                    "untuk memilih pengajuan."
                ),
            }

        # ---------------------------------------------
        # No candidate yet:
        # typed trigger pre-approves next valid write.
        # ---------------------------------------------

        self.set_preapproval(
            identity
        )

        return {
            "action": "rewrite",
            "text": (
                "[ARDILES VERIFIED SKILL PRE-APPROVAL]\n"
                "Telegram user yang diotorisasi telah "
                "memberikan approval eksplisit. "
                "Buat/update learning relevan menggunakan "
                "skill_manage. Payload WAJIB valid sebelum "
                "disimpan. Jangan meminta approval kedua. "
                "Setelah sukses WAJIB konfirmasi nama skill "
                "dan isi yang disimpan."
            ),
        }

    # =====================================================
    # LLM POLICY
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
                "- JANGAN gunakan clarify untuk approval skill.\n"
                "- Gunakan skill_manage untuk menyiapkan perubahan.\n"
                "- Jika skill_manage menghasilkan "
                "skill_preflight_failed, perbaiki payload dan "
                "panggil skill_manage lagi SEBELUM approval manusia.\n"
                "- Jika skill_manage menghasilkan "
                "ready_for_human_approval=true, segera panggil "
                "request_skill_approval dengan pending_id tersebut.\n"
                "- request_skill_approval menampilkan tombol native "
                "Telegram Update Skill / Batal.\n"
                "- Jangan mengatakan sudah tersimpan selama "
                "awaiting_human_approval=true.\n"
                "- 'update skill' atau 'simpan skill' dari user "
                "authorized adalah approval eksplisit.\n"
                "- 'pending skill' dikelola langsung oleh native "
                "Telegram UI dan tidak membutuhkan tool call.\n"
                "- Setelah benar-benar tersimpan, WAJIB konfirmasi "
                "nama skill dan isi/rule/framework yang disimpan."
            )
        }

    # =====================================================
    # SKILL_MANAGE RESULT INTERCEPTOR
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

        # ---------------------------------------------
        # Only Randy / Andreas Telegram IDs can
        # create actual skill changes.
        # ---------------------------------------------

        if not self.is_authorized(
            identity
        ):
            self.discard_pending(
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

        record = self.get_pending(
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

        # ---------------------------------------------
        # PRE-VALIDATE BEFORE HUMAN APPROVAL.
        #
        # This prevents another:
        # "Approve -> description too long -> Approve again"
        # flow.
        # ---------------------------------------------

        validation_error = (
            self.preflight_payload(
                record.get(
                    "payload"
                )
                or {}
            )
        )

        if validation_error:
            self.discard_pending(
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
                        "JANGAN meminta approval manusia "
                        "sebelum payload valid."
                    ),
                },
                ensure_ascii=False
            )

        self.save_candidate(
            pending_id,
            identity,
            record
        )

        # ---------------------------------------------
        # User already typed:
        #
        # update skill
        # simpan skill
        #
        # so do not ask twice.
        # ---------------------------------------------

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
