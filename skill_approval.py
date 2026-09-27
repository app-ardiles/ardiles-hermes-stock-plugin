import asyncio
import json
import logging
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


logger = logging.getLogger(__name__)


# =========================================================
# ARDILES SECURE SKILL APPROVAL
# =========================================================

CARD_TTL_SECONDS = 60

STATE_KEY = "skill_update_candidates"
PREAPPROVAL_KEY = "skill_update_preapprovals"

PREAPPROVAL_TTL_SECONDS = 180
CANDIDATE_TTL_SECONDS = 7 * 24 * 60 * 60


PENDING_TRIGGERS = {
    "pending skill",
    "pending skills",
    "skill pending",
}


REQUEST_SKILL_APPROVAL = {
    "name": "request_skill_approval",
    "description": (
        "Show native Telegram Update Skill / Batal buttons for one "
        "validated staged Ardiles skill write. "
        "Call only after skill_manage returns "
        "ready_for_human_approval=true. "
        "Never use clarify for Ardiles skill approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pending_id": {
                "type": "string",
                "description": (
                    "Pending skill ID returned by skill_manage."
                ),
            },
        },
        "required": [
            "pending_id"
        ],
    },
}


# =========================================================
# BASIC HELPERS
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


def _is_update_trigger(
    text: str
) -> bool:
    text = _normalize_text(
        text
    )

    if text in {
        "update skill",
        "simpan skill",
    }:
        return True

    patterns = (
        r"\b(?:update|simpan|save|keep)\b.*\bskill\b",
        r"\bskill\b.*\b(?:update|simpan|save|keep)\b",
    )

    return any(
        re.search(
            pattern,
            text,
            re.IGNORECASE
        )
        for pattern in patterns
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

        # ctx.state.data_dir:
        #
        # <PROFILE_HOME>/plugin-data/<plugin-namespace>
        #
        # We capture the profile home during plugin
        # registration so native Telegram callbacks can
        # safely return to the ardiles-stock profile.
        self.profile_home = Path(
            ctx.state.data_dir
        ).parent.parent.resolve()

        self.telegram_application = None
        self.telegram_loop = None

        # Runtime-only generation tracking.
        #
        # Used so an old 60-second expiry task cannot
        # remove buttons from a card that was refreshed
        # by Previous / Next.
        #
        # key:
        #   (chat_id, message_id)
        #
        # value:
        #   issued_ms
        self._card_generations: Dict[
            tuple[str, str],
            str
        ] = {}

    # =====================================================
    # PROFILE SCOPE
    # =====================================================

    @contextmanager
    def profile_scope(
        self
    ):
        token = (
            set_hermes_home_override(
                str(
                    self.profile_home
                )
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
            )
            in self.authorized_ids()
        )

    # =====================================================
    # PENDING STORE
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
    # CANDIDATE STORE
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
        record: Dict[str, Any],
    ) -> None:
        candidates = (
            self.load_candidates()
        )

        payload = (
            record.get(
                "payload"
            )
            or {}
        )

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
        candidates = (
            self.load_candidates()
        )

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
        matches = []

        for candidate in (
            self.load_candidates()
            .values()
        ):
            if (
                candidate.get(
                    "platform"
                )
                !=
                identity.get(
                    "platform"
                )
            ):
                continue

            if (
                candidate.get(
                    "user_id"
                )
                !=
                identity.get(
                    "user_id"
                )
            ):
                continue

            if (
                candidate.get(
                    "chat_id"
                )
                !=
                identity.get(
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

            matches.append(
                candidate
            )

        matches.sort(
            key=lambda item:
                float(
                    item.get(
                        "created_at"
                    )
                    or 0
                ),
            reverse=True
        )

        return matches

    # =====================================================
    # PREAPPROVAL STORE
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
        data = (
            self.load_preapprovals()
        )

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
        data = (
            self.load_preapprovals()
        )

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
    # PAYLOAD DISPLAY HELPERS
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
        return ", ".join(
            self.payload_skill_names(
                payload
            )
        )

    def operations_text(
        self,
        payload: Dict[str, Any]
    ) -> str:
        if (
            payload.get(
                "action"
            ) != "batch"
        ):
            return (
                f"{payload.get('action') or '-'}"
                f" — "
                f"{payload.get('name') or '-'}"
            )

        lines = []

        for (
            index,
            operation
        ) in enumerate(
            payload.get(
                "operations"
            )
            or [],
            start=1
        ):
            if not isinstance(
                operation,
                dict
            ):
                continue

            action = (
                operation.get(
                    "action"
                )
                or "-"
            )

            name = (
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
        max_chars: int = 2400
    ) -> str:
        payload = (
            record.get(
                "payload"
            )
            or {}
        )

        action = (
            payload.get(
                "action"
            )
            or ""
        )

        texts = []

        if action == "batch":
            for operation in (
                payload.get(
                    "operations"
                )
                or []
            ):
                if not isinstance(
                    operation,
                    dict
                ):
                    continue

                op_action = (
                    operation.get(
                        "action"
                    )
                    or ""
                )

                name = (
                    operation.get(
                        "name"
                    )
                    or ""
                )

                if op_action in {
                    "create",
                    "edit",
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
                    content = str(
                        operation.get(
                            "new_string"
                        )
                        or
                        operation.get(
                            "content"
                        )
                        or ""
                    ).strip()

                    if content:
                        texts.append(
                            f"[{name}]\n{content}"
                        )

                elif op_action == "write_file":
                    content = str(
                        operation.get(
                            "file_content"
                        )
                        or ""
                    ).strip()

                    if content:
                        texts.append(
                            f"[{name} / "
                            f"{operation.get('file_path') or 'file'}]"
                            f"\n{content}"
                        )

        elif action in {
            "create",
            "edit",
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
        planned_creates=None,
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
        if (
            str(
                payload.get(
                    "action"
                )
                or ""
            )
            != "batch"
        ):
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

        planned_creates = set()

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

                error = (
                    self.preflight_operation(
                        operation,
                        planned_creates=planned_creates,
                    )
                )

                if error:
                    return (
                        f"operations[{index}]: "
                        f"{error}"
                    )

                if (
                    operation.get(
                        "action"
                    ) == "create"
                ):
                    name = str(
                        operation.get(
                            "name"
                        )
                        or ""
                    ).strip()

                    if name:
                        planned_creates.add(
                            name
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
                    "Pending skill sudah tidak tersedia.",
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
                    result.get(
                        "error"
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
    # CARD EXPIRY
    # =====================================================

    def _issued_ms(
        self
    ) -> str:
        return str(
            int(
                time.time()
                * 1000
            )
        )

    def _is_expired(
        self,
        issued_ms: str
    ) -> bool:
        try:
            issued = int(
                issued_ms
            )

        except Exception:
            return True

        age_ms = (
            int(
                time.time()
                * 1000
            )
            - issued
        )

        return (
            age_ms < 0
            or
            age_ms
            > CARD_TTL_SECONDS
            * 1000
        )

    def _card_key(
        self,
        message
    ) -> tuple[str, str]:
        chat_id = str(
            getattr(
                getattr(
                    message,
                    "chat",
                    None
                ),
                "id",
                ""
            )
            or ""
        )

        message_id = str(
            getattr(
                message,
                "message_id",
                ""
            )
            or ""
        )

        return (
            chat_id,
            message_id
        )

    def _remember_card_generation(
        self,
        message,
        issued_ms: str
    ) -> None:
        self._card_generations[
            self._card_key(
                message
            )
        ] = issued_ms

    def _clear_card_generation(
        self,
        message
    ) -> None:
        self._card_generations.pop(
            self._card_key(
                message
            ),
            None
        )

    async def _expire_card_after(
        self,
        message,
        issued_ms: str,
        expired_text: str,
    ) -> None:
        await asyncio.sleep(
            CARD_TTL_SECONDS
        )

        key = self._card_key(
            message
        )

        # The card has been refreshed with a new
        # generation, so this old expiry task must
        # not touch it.
        if (
            self._card_generations.get(
                key
            )
            != issued_ms
        ):
            return

        try:
            await message.edit_text(
                text=expired_text,
                reply_markup=None,
            )

        except Exception as exc:
            logger.warning(
                "Could not expire Ardiles "
                "skill card: %s",
                exc,
            )

        finally:
            if (
                self._card_generations.get(
                    key
                )
                == issued_ms
            ):
                self._card_generations.pop(
                    key,
                    None
                )

    def _schedule_card_expiry(
        self,
        message,
        issued_ms: str,
        expired_text: str,
    ) -> None:
        self._remember_card_generation(
            message,
            issued_ms
        )

        coroutine = (
            self._expire_card_after(
                message,
                issued_ms,
                expired_text,
            )
        )

        try:
            current_loop = (
                asyncio.get_running_loop()
            )

            # request_skill_approval may run from
            # an agent execution loop different from
            # Telegram's polling loop.
            if (
                self.telegram_loop
                is not None
                and
                not self.telegram_loop.is_closed()
                and
                current_loop
                is not self.telegram_loop
            ):
                asyncio.run_coroutine_threadsafe(
                    coroutine,
                    self.telegram_loop
                )

            else:
                current_loop.create_task(
                    coroutine
                )

        except Exception:
            coroutine.close()

            logger.exception(
                "Failed to schedule Ardiles "
                "skill card expiry"
            )

    async def _expire_clicked_card_now(
        self,
        query,
        *,
        pending_id: str = "",
    ) -> None:
        record = (
            self.get_pending(
                pending_id
            )
            if pending_id
            else None
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
                or ""
            )

        if skill_name:
            title = (
                "⌛ Approval kedaluwarsa\n\n"
                f"Nama skill: "
                f"{skill_name}\n\n"
            )

        else:
            title = (
                "⌛ Kartu pending skill "
                "kedaluwarsa\n\n"
            )

        text = (
            title
            + "Tombol hanya berlaku 1 menit.\n"
            "Pending tetap tersimpan.\n\n"
            + 'Ketik "pending skill" '
            "untuk membuka kembali."
        )

        self._clear_card_generation(
            getattr(
                query,
                "message",
                None
            )
        )

        try:
            await query.edit_message_text(
                text=text,
                reply_markup=None,
            )

        except Exception:
            logger.exception(
                "Failed to expire clicked "
                "Ardiles skill card"
            )

    # =====================================================
    # TELEGRAM REGISTRATION
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

        self.telegram_application = (
            application
        )

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
            await self.handle_button(
                update
            )

        application.add_handler(
            CallbackQueryHandler(
                on_button,
                pattern=r"^ardiles_skill:",
            )
        )

        async def on_pending(
            update,
            context
        ):
            await self.handle_pending_command(
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
                        re.IGNORECASE,
                    )
                ),
                on_pending,
            )
        )

        logger.info(
            "Ardiles Telegram skill approval "
            "handlers wired for profile %s",
            self.profile_home,
        )

    # =====================================================
    # TELEGRAM LOOP BRIDGE
    # =====================================================

    async def run_on_telegram_loop(
        self,
        coroutine
    ):
        if (
            self.telegram_loop
            is None
            or
            self.telegram_loop.is_closed()
        ):
            raise RuntimeError(
                "Telegram gateway loop "
                "is unavailable."
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
    # REQUEST APPROVAL TOOL
    # =====================================================

    async def request_skill_approval(
        self,
        args,
        **kwargs,
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
                ensure_ascii=False,
            )

        identity = (
            self.session_identity()
        )

        if not self.is_authorized(
            identity
        ):
            return json.dumps(
                {
                    "success": False,
                    "saved": False,
                    "error":
                        "skill_update_not_authorized",
                },
                ensure_ascii=False,
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
                ensure_ascii=False,
            )

        if (
            candidate.get(
                "user_id"
            )
            !=
            identity.get(
                "user_id"
            )
            or
            candidate.get(
                "chat_id"
            )
            !=
            identity.get(
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
                ensure_ascii=False,
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
                ensure_ascii=False,
            )

        await self.send_direct_card(
            identity,
            record
        )

        return json.dumps(
            {
                "success": True,
                "saved": False,

                "awaiting_human_approval":
                    True,

                "approval_expires_seconds":
                    CARD_TTL_SECONDS,

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
                    "Tombol approval native Telegram "
                    "sudah dikirim dan berlaku 1 menit. "
                    "Pending tetap tersimpan jika tombol "
                    "kedaluwarsa. Balas singkat saja bahwa "
                    "approval menunggu tombol."
                ),
            },
            ensure_ascii=False,
        )

    async def send_direct_card(
        self,
        identity,
        record
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

        skill_name = (
            self.payload_skill_name(
                record.get(
                    "payload"
                )
                or {}
            )
            or "-"
        )

        preview = (
            self.saved_content(
                record,
                max_chars=1800
            )
            or "-"
        )

        issued_ms = (
            self._issued_ms()
        )

        text = (
            "🧠 Learning siap disimpan\n\n"
            f"Nama skill: {skill_name}\n\n"
            "Isi / perubahan:\n"
            f"{preview}\n\n"
            "⏳ Tombol akan hilang dalam 1 menit.\n"
            "Setelah itu tombol tidak dapat digunakan.\n"
            "Pending tetap tersimpan.\n\n"
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
                            f"{pending_id}:"
                            f"{issued_ms}"
                        ),
                    ),

                    InlineKeyboardButton(
                        "❌ Batal",
                        callback_data=(
                            "ardiles_skill:"
                            "direct_cancel:"
                            f"{pending_id}:"
                            f"{issued_ms}"
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

        sent = (
            await self.run_on_telegram_loop(
                self.telegram_application
                .bot
                .send_message(
                    **send_kwargs
                )
            )
        )

        expired_text = (
            "⌛ Approval kedaluwarsa\n\n"
            f"Nama skill: {skill_name}\n\n"
            "Tombol hanya berlaku 1 menit.\n"
            "Pending tetap tersimpan.\n\n"
            'Ketik "pending skill" '
            "untuk membuka kembali."
        )

        self._schedule_card_expiry(
            sent,
            issued_ms,
            expired_text,
        )

    # =====================================================
    # PENDING SKILL COMMAND
    # =====================================================

    async def handle_pending_command(
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
                "melihat atau menyetujui "
                "pending skill."
            )

            return

        await self.send_pending_page(
            message=message,
            page=0,
        )

    async def send_pending_page(
        self,
        *,
        message=None,
        query=None,
        page=0,
    ) -> bool:
        from telegram import (
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        records = (
            self.list_pending()
        )

        if not records:
            text = (
                "✅ Tidak ada pending skill."
            )

            if query is not None:
                try:
                    await query.edit_message_text(
                        text=text,
                        reply_markup=None,
                    )

                    return True

                except Exception as exc:
                    logger.warning(
                        "Could not update empty "
                        "pending card: %s",
                        exc,
                    )

                    return False

            if message is not None:
                await message.reply_text(
                    text
                )

                return True

            return False

        total = len(
            records
        )

        page = int(
            page
        ) % total

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

        preview = (
            self.saved_content(
                record,
                max_chars=1200
            )
            or "-"
        )

        issued_ms = (
            self._issued_ms()
        )

        text = (
            "🧠 Pending Skill\n\n"
            f"{page + 1} dari {total}\n\n"
            f"ID: {pending_id}\n"
            f"Nama skill: {skill_name}\n\n"
            "Ringkasan:\n"
            f"{summary}\n\n"
            "Operasi:\n"
            f"{self.operations_text(payload)}\n\n"
            "Isi / perubahan:\n"
            f"{preview}\n\n"
            "⏳ Tombol akan hilang dalam 1 menit.\n"
            "Setelah itu tombol tidak dapat digunakan.\n"
            "Pending tetap tersimpan."
        )

        rows = [
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=(
                        "ardiles_skill:"
                        "review_approve:"
                        f"{pending_id}:"
                        f"{issued_ms}"
                    ),
                ),

                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=(
                        "ardiles_skill:"
                        "review_reject:"
                        f"{pending_id}:"
                        f"{issued_ms}"
                    ),
                ),
            ]
        ]

        if total > 1:
            rows.append(
                [
                    InlineKeyboardButton(
                        "⬅️ Sebelumnya",
                        callback_data=(
                            "ardiles_skill:"
                            "review_page:"
                            f"{(page - 1) % total}:"
                            f"{issued_ms}"
                        ),
                    ),

                    InlineKeyboardButton(
                        "➡️ Berikutnya",
                        callback_data=(
                            "ardiles_skill:"
                            "review_page:"
                            f"{(page + 1) % total}:"
                            f"{issued_ms}"
                        ),
                    ),
                ]
            )

        keyboard = InlineKeyboardMarkup(
            rows
        )

        expired_text = (
            "⌛ Kartu pending skill kedaluwarsa\n\n"
            f"Terakhir ditampilkan: "
            f"{skill_name}\n\n"
            "Tombol hanya berlaku 1 menit.\n"
            "Pending tetap tersimpan.\n\n"
            'Ketik "pending skill" '
            "untuk membuka kembali."
        )

        if query is not None:
            # IMPORTANT:
            #
            # Previous / Next only edits THIS SAME card.
            #
            # We intentionally do NOT send a fallback
            # card as a new Telegram message.
            try:
                await query.edit_message_text(
                    text=text,
                    reply_markup=keyboard,
                )

                edited_message = (
                    query.message
                )

                self._schedule_card_expiry(
                    edited_message,
                    issued_ms,
                    expired_text,
                )

                return True

            except Exception as exc:
                logger.warning(
                    "Could not edit pending "
                    "skill card: %s",
                    exc,
                )

                return False

        if message is not None:
            sent = await message.reply_text(
                text=text,
                reply_markup=keyboard,
            )

            self._schedule_card_expiry(
                sent,
                issued_ms,
                expired_text,
            )

            return True

        return False

    # =====================================================
    # BUTTON CALLBACK
    # =====================================================

    async def handle_button(
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
            ":"
        )

        # Format:
        #
        # ardiles_skill:<action>:<value>:<issued_ms>

        if len(
            parts
        ) != 4:
            return

        (
            prefix,
            action,
            value,
            issued_ms,
        ) = parts

        if prefix != "ardiles_skill":
            return

        user_id = str(
            getattr(
                getattr(
                    update,
                    "effective_user",
                    None
                ),
                "id",
                ""
            )
            or ""
        )

        chat_id = str(
            getattr(
                getattr(
                    update,
                    "effective_chat",
                    None
                ),
                "id",
                ""
            )
            or ""
        )

        logger.info(
            "Ardiles skill callback: "
            "action=%s value=%s issued_ms=%s "
            "telegram_user=%s chat=%s",
            action,
            value,
            issued_ms,
            user_id,
            chat_id,
        )

        if not self.is_authorized_user_id(
            user_id
        ):
            await query.answer(
                "Anda tidak memiliki "
                "hak update skill.",
                show_alert=True,
            )

            return

        # ---------------------------------------------
        # HARD SERVER-SIDE EXPIRY
        #
        # Even if Telegram visually still shows an
        # old button, it cannot mutate a skill after
        # 60 seconds.
        # ---------------------------------------------

        if self._is_expired(
            issued_ms
        ):
            await query.answer(
                "Approval sudah kedaluwarsa. "
                'Ketik "pending skill" '
                "untuk membuka kembali.",
                show_alert=True,
            )

            pending_id = (
                value
                if action != "review_page"
                else ""
            )

            await self._expire_clicked_card_now(
                query,
                pending_id=pending_id,
            )

            return

        # ---------------------------------------------
        # PREVIOUS / NEXT
        # ---------------------------------------------

        if action == "review_page":
            try:
                page = int(
                    value
                )

            except Exception:
                page = 0

            ok = await self.send_pending_page(
                query=query,
                page=page,
            )

            if ok:
                await query.answer()

            else:
                await query.answer(
                    "Kartu gagal diperbarui. "
                    'Ketik "pending skill" lagi.',
                    show_alert=True,
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
                "Pending ini sudah "
                "tidak tersedia.",
                show_alert=True,
            )

            return

        # ---------------------------------------------
        # DIRECT CARD OWNER CHECK
        # ---------------------------------------------

        if action in {
            "direct_approve",
            "direct_cancel",
        }:
            candidate = (
                self.load_candidates()
                .get(
                    pending_id
                )
            )

            if not candidate:
                await query.answer(
                    "Pengajuan ini sudah "
                    "tidak tersedia.",
                    show_alert=True,
                )

                return

            if (
                candidate.get(
                    "user_id"
                )
                != user_id
                or
                candidate.get(
                    "chat_id"
                )
                != chat_id
            ):
                await query.answer(
                    "Approval ini bukan "
                    "milik user/chat ini.",
                    show_alert=True,
                )

                return

        # This card is being resolved now.
        #
        # Prevent the old 60-second expiry task
        # from overwriting the completed status.
        self._clear_card_generation(
            getattr(
                query,
                "message",
                None
            )
        )

        await query.answer()

        # ---------------------------------------------
        # DIRECT CANCEL
        # ---------------------------------------------

        if action == "direct_cancel":
            result = (
                self.reject_pending(
                    pending_id
                )
            )

            await self.edit_status_only(
                query,
                (
                    "❌ Update skill dibatalkan\n\n"
                    "Nama skill: "
                    f"{result.get('skill_name') or '-'}"
                ),
            )

            return

        # ---------------------------------------------
        # DIRECT APPROVE
        # ---------------------------------------------

        if action == "direct_approve":
            result = (
                self.apply_pending(
                    pending_id
                )
            )

            await self.show_apply_result(
                query,
                result,
                show_next=False,
            )

            return

        # ---------------------------------------------
        # REVIEW REJECT
        # ---------------------------------------------

        if action == "review_reject":
            result = (
                self.reject_pending(
                    pending_id
                )
            )

            has_next = bool(
                self.list_pending()
            )

            text = (
                "❌ Pending skill ditolak\n\n"
                "Nama skill: "
                f"{result.get('skill_name') or '-'}\n"
                f"ID: {pending_id}"
            )

            await self.edit_review_status(
                query,
                text=text,
                has_next=has_next,
            )

            return

        # ---------------------------------------------
        # REVIEW APPROVE
        # ---------------------------------------------

        if action == "review_approve":
            result = (
                self.apply_pending(
                    pending_id
                )
            )

            await self.show_apply_result(
                query,
                result,
                show_next=True,
            )

            return

    # =====================================================
    # RESULT DISPLAY
    # =====================================================

    async def show_apply_result(
        self,
        query,
        result: Dict[str, Any],
        *,
        show_next: bool,
    ):
        if not result.get(
            "saved"
        ):
            reason = (
                result.get(
                    "message"
                )
                or
                result.get(
                    "error"
                )
                or
                "Unknown error"
            )

            await self.edit_review_status(
                query,
                text=(
                    "⚠️ Skill belum tersimpan\n\n"
                    "Alasan:\n"
                    f"{reason}"
                ),
                has_next=(
                    show_next
                    and
                    bool(
                        self.list_pending()
                    )
                ),
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

        # The original card becomes a short
        # completed status.
        await self.edit_review_status(
            query,
            text=(
                "✅ Approval selesai\n\n"
                f"Nama skill: "
                f"{skill_name}\n"
                "Status: tersimpan."
            ),
            has_next=(
                show_next
                and
                bool(
                    self.list_pending()
                )
            ),
        )

        # IMPORTANT:
        #
        # Send a NEW Telegram message at the bottom.
        #
        # This makes the successful result obvious
        # instead of only changing an older message
        # higher up in the chat.
        message = getattr(
            query,
            "message",
            None
        )

        if message is not None:
            try:
                await message.reply_text(
                    "✅ Skill berhasil disimpan\n\n"
                    f"Nama skill: "
                    f"{skill_name}\n\n"
                    "Isi yang disimpan:\n"
                    f"{saved_content}"
                )

                logger.info(
                    "Ardiles skill approval confirmation "
                    "sent as fresh Telegram message"
                )

            except Exception:
                logger.exception(
                    "Failed to send fresh Ardiles "
                    "skill approval confirmation"
                )

    async def edit_status_only(
        self,
        query,
        text: str,
    ):
        self._clear_card_generation(
            getattr(
                query,
                "message",
                None
            )
        )

        try:
            await query.edit_message_text(
                text=text,
                reply_markup=None,
            )

        except Exception:
            logger.exception(
                "Failed to edit Ardiles "
                "skill status card"
            )

    async def edit_review_status(
        self,
        query,
        *,
        text: str,
        has_next: bool,
    ):
        from telegram import (
            InlineKeyboardButton,
            InlineKeyboardMarkup,
        )

        keyboard = None

        issued_ms = None

        if has_next:
            issued_ms = (
                self._issued_ms()
            )

            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "➡️ Pending Berikutnya",
                            callback_data=(
                                "ardiles_skill:"
                                "review_page:"
                                "0:"
                                f"{issued_ms}"
                            ),
                        )
                    ]
                ]
            )

        if keyboard is None:
            self._clear_card_generation(
                getattr(
                    query,
                    "message",
                    None
                )
            )

        try:
            await query.edit_message_text(
                text=text,
                reply_markup=keyboard,
            )

            if (
                keyboard is not None
                and
                issued_ms is not None
            ):
                message = query.message

                self._schedule_card_expiry(
                    message,
                    issued_ms,
                    (
                        f"{text}\n\n"
                        "⌛ Tombol Pending Berikutnya "
                        "sudah kedaluwarsa.\n"
                        'Ketik "pending skill" '
                        "untuk membuka kembali."
                    ),
                )

        except Exception:
            logger.exception(
                "Failed to edit Ardiles "
                "skill review card"
            )

    # =====================================================
    # NATURAL TEXT FALLBACK
    # =====================================================

    def pre_gateway_dispatch(
        self,
        event,
        **kwargs,
    ):
        identity = (
            self.event_identity(
                event
            )
        )

        raw_text = str(
            getattr(
                event,
                "text",
                "",
            )
            or ""
        ).strip()

        normalized = (
            _normalize_text(
                raw_text
            )
        )

        # ---------------------------------------------
        # Protect native Hermes /skills commands.
        # ---------------------------------------------

        if re.match(
            r"^/skills(?:@\w+)?(?:\s|$)",
            raw_text,
            re.I,
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
                    "action":
                        "rewrite",

                    "text": (
                        "Permintaan perubahan skill "
                        "ditolak. Telegram user ini "
                        "tidak memiliki hak update "
                        "skill bersama."
                    ),
                }

            return None

        # Native Telegram MessageHandler owns
        # pending skill.
        if normalized in PENDING_TRIGGERS:
            return None

        if not _is_update_trigger(
            normalized
        ):
            return None

        if not self.is_authorized(
            identity
        ):
            return {
                "action":
                    "rewrite",

                "text": (
                    "Permintaan update skill ditolak. "
                    "Telegram user ini tidak memiliki "
                    "hak update skill bersama."
                ),
            }

        candidates = (
            self.matching_candidates(
                identity
            )
        )

        # ---------------------------------------------
        # One LIVE candidate owned by this
        # human/chat:
        #
        # typed update skill / simpan skill itself
        # is the approval.
        # ---------------------------------------------

        if len(
            candidates
        ) == 1:
            result = (
                self.apply_pending(
                    candidates[
                        0
                    ][
                        "pending_id"
                    ]
                )
            )

            return {
                "action":
                    "rewrite",

                "text": (
                    "[ARDILES VERIFIED "
                    "SKILL APPROVAL]\n"
                    + json.dumps(
                        result,
                        ensure_ascii=False,
                    )
                    + "\nJika saved=true, "
                    "WAJIB konfirmasi nama skill "
                    "dan isi yang disimpan. "
                    "Jangan panggil skill_manage lagi."
                ),
            }

        if len(
            candidates
        ) > 1:
            return {
                "action":
                    "rewrite",

                "text": (
                    "Ada lebih dari satu pengajuan "
                    "skill aktif untuk chat ini. "
                    "Jangan menyimpan apa pun. "
                    'Minta user mengetik "pending skill" '
                    "untuk memilih pengajuan."
                ),
            }

        # ---------------------------------------------
        # No LIVE candidate.
        #
        # The natural-language approval applies
        # to the next valid skill write.
        # ---------------------------------------------

        self.set_preapproval(
            identity
        )

        return {
            "action":
                "rewrite",

            "text": (
                "[ARDILES VERIFIED "
                "SKILL PRE-APPROVAL]\n"
                "User Telegram yang diotorisasi "
                "sudah memberi approval eksplisit. "
                "Buat/update learning relevan "
                "menggunakan skill_manage. "
                "Jangan meminta approval kedua. "
                "Setelah sukses WAJIB konfirmasi "
                "nama skill dan isi yang disimpan."
            ),
        }

    # =====================================================
    # LIVE AUTHORITATIVE STATE FOR LLM
    # =====================================================

    def pre_llm_call(
        self,
        session_id="",
        user_message="",
        platform="",
        sender_id="",
        **kwargs,
    ):
        identity = (
            self.session_identity()
        )

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

        if session_id:
            identity[
                "session_id"
            ] = str(
                session_id
            ).strip()

        if not self.is_authorized(
            identity
        ):
            return None

        # -------------------------------------------------
        # ACTUAL PENDING STATE
        #
        # This is the source of truth.
        #
        # Old chat messages saying "still waiting"
        # must NOT override this current state.
        # -------------------------------------------------

        profile_pending = (
            self.list_pending()
        )

        chat_candidates = (
            self.matching_candidates(
                identity
            )
        )

        live_names = []

        for record in profile_pending[
            :20
        ]:
            name = (
                self.payload_skill_name(
                    record.get(
                        "payload"
                    )
                    or {}
                )
            )

            if (
                name
                and
                name not in live_names
            ):
                live_names.append(
                    name
                )

        if live_names:
            pending_summary = ", ".join(
                live_names[
                    :8
                ]
            )

        else:
            pending_summary = "(none)"

        context = (
            "ARDILES SKILL APPROVAL POLICY "
            "— LIVE AUTHORITATIVE STATE:\n"

            f"- Current profile pending count: "
            f"{len(profile_pending)}.\n"

            f"- Current pending names (up to 8): "
            f"{pending_summary}.\n"

            f"- Current pending candidates owned "
            f"by THIS Telegram human/chat: "
            f"{len(chat_candidates)}.\n"

            "- This LIVE state overrides old "
            "assistant/chat-history statements "
            "about whether a previous skill is "
            "still waiting for approval.\n"

            "- If THIS chat has 0 owned candidates, "
            "DO NOT block a new skill request merely "
            "because an older assistant message said "
            "a previous request was pending.\n"

            "- Other profile-level pending records "
            "do NOT block this human from preparing "
            "a new skill. They are reviewed separately "
            "with 'pending skill'.\n"

            "- Never use clarify for Ardiles "
            "skill approval.\n"

            "- Use skill_manage to prepare "
            "the skill write.\n"

            "- If skill_manage returns "
            "skill_preflight_failed, fix the payload "
            "BEFORE asking for human approval.\n"

            "- If skill_manage returns "
            "ready_for_human_approval=true, call "
            "request_skill_approval with that "
            "pending_id.\n"

            "- request_skill_approval sends native "
            "Telegram Update Skill / Batal buttons.\n"

            "- Every approval card clearly warns "
            "that buttons expire after 1 minute.\n"

            "- After 1 minute, buttons are invalid "
            "server-side and are removed when possible. "
            "The pending record remains stored.\n"

            "- After request_skill_approval succeeds, "
            "reply only briefly that approval is "
            "waiting on the button. Do not repeat the "
            "long skill body.\n"

            "- After a real save succeeds, always "
            "confirm the actual skill name and the "
            "content/rule/framework that was saved.\n"

            "- 'pending skill' is handled by native "
            "Telegram UI without an LLM tool call."
        )

        return {
            "context":
                context
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
        **kwargs,
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

        identity = (
            self.session_identity()
        )

        if session_id:
            identity[
                "session_id"
            ] = str(
                session_id
            )

        # ---------------------------------------------
        # Unauthorized writes never survive staging.
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
                    "message": (
                        "Skill tidak disimpan. "
                        "User tidak berwenang."
                    ),
                },
                ensure_ascii=False,
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
                ensure_ascii=False,
            )

        # ---------------------------------------------
        # Validate BEFORE human sees approval buttons.
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
                        "Perbaiki lalu panggil "
                        "skill_manage lagi. "
                        "Jangan meminta approval "
                        "manusia dahulu."
                    ),
                },
                ensure_ascii=False,
            )

        self.save_candidate(
            pending_id,
            identity,
            record,
        )

        # ---------------------------------------------
        # Human already typed:
        #
        # update skill
        # simpan skill
        #
        # Do not ask twice.
        # ---------------------------------------------

        if self.consume_preapproval(
            identity
        ):
            return json.dumps(
                self.apply_pending(
                    pending_id
                ),
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "success": True,
                "saved": False,
                "staged": True,

                "ready_for_human_approval":
                    True,

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
                    "Panggil request_skill_approval "
                    "dengan pending_id ini. "
                    "Jangan gunakan clarify."
                ),
            },
            ensure_ascii=False,
        )
