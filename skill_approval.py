import json
import re
import time
from typing import Any, Dict, List

from gateway.session_context import get_session_env
from tools import write_approval as wa
from tools.skill_manager_tool import apply_skill_pending


# =========================================================
# Ardiles guarded skill approval
#
# Security model:
# - skills.write_approval tetap ON
# - skill_manage tetap membuat staged/pending write
# - hanya Telegram user ID yang di-whitelist boleh approve
# - natural trigger harus PERSIS "update skill" / "simpan skill"
# - Telegram button memakai built-in clarify tool
# =========================================================

TRIGGERS = {
    "update skill",
    "simpan skill",
}

STATE_KEY = "skill_update_candidates"
PREAPPROVAL_KEY = "skill_update_preapprovals"

PREAPPROVAL_TTL_SECONDS = 180
CANDIDATE_TTL_SECONDS = 7 * 24 * 60 * 60


# =========================================================
# Basic helpers
# =========================================================

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
        value
    )

    return str(
        raw or ""
    ).strip().lower()


def _authorized_ids(ctx) -> set[str]:
    raw = ctx.get_config(
        "skill_update_telegram_ids",
        ""
    )

    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(
            r"[\s,;]+",
            str(raw or "")
        )

    return {
        str(item).strip()
        for item in items
        if str(item).strip().isdigit()
    }


def _session_identity() -> Dict[str, str]:
    platform = (
        get_session_env(
            "HERMES_SESSION_PLATFORM",
            ""
        )
        or get_session_env(
            "HERMES_SESSION_SOURCE",
            ""
        )
    )

    return {
        "platform": _platform_name(
            platform
        ),
        "user_id": str(
            get_session_env(
                "HERMES_SESSION_USER_ID",
                ""
            )
            or ""
        ).strip(),
        "chat_id": str(
            get_session_env(
                "HERMES_SESSION_CHAT_ID",
                ""
            )
            or ""
        ).strip(),
        "thread_id": str(
            get_session_env(
                "HERMES_SESSION_THREAD_ID",
                ""
            )
            or ""
        ).strip(),
        "session_id": str(
            get_session_env(
                "HERMES_SESSION_ID",
                ""
            )
            or ""
        ).strip(),
    }


def _event_identity(event) -> Dict[str, str]:
    source = getattr(
        event,
        "source",
        None
    )

    return {
        "platform": _platform_name(
            getattr(
                source,
                "platform",
                ""
            )
        ),
        "user_id": str(
            getattr(
                source,
                "user_id",
                ""
            )
            or ""
        ).strip(),
        "chat_id": str(
            getattr(
                source,
                "chat_id",
                ""
            )
            or ""
        ).strip(),
        "thread_id": str(
            getattr(
                source,
                "thread_id",
                ""
            )
            or ""
        ).strip(),
        "session_id": "",
    }


def _is_authorized(
    ctx,
    identity: Dict[str, str]
) -> bool:
    return (
        identity.get(
            "platform"
        ) == "telegram"
        and identity.get(
            "user_id"
        ) in _authorized_ids(ctx)
    )


def _load_json_result(
    result: Any
) -> Dict[str, Any]:
    if isinstance(
        result,
        dict
    ):
        return dict(result)

    if not isinstance(
        result,
        str
    ):
        return {}

    try:
        parsed = json.loads(
            result
        )
    except Exception:
        return {}

    if isinstance(
        parsed,
        dict
    ):
        return parsed

    return {}


# =========================================================
# Saved content summary
# =========================================================

def _saved_content(
    record: Dict[str, Any],
    max_chars: int = 3500
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

    if action == "patch":
        text = (
            payload.get(
                "new_string"
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
        return (
            text[:max_chars].rstrip()
            + "\n…"
        )

    return text


# =========================================================
# Pending candidate storage
# =========================================================

def _load_candidates(
    ctx
) -> Dict[str, Dict[str, Any]]:
    raw = ctx.state.get(
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
        ctx.state.set(
            STATE_KEY,
            cleaned
        )

    return cleaned


def _save_candidate(
    ctx,
    pending_id: str,
    identity: Dict[str, str],
    *,
    turn_id: str = ""
) -> None:
    candidates = _load_candidates(
        ctx
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

        "turn_id":
            str(
                turn_id
                or ""
            ),

        "created_at":
            time.time(),
    }

    ctx.state.set(
        STATE_KEY,
        candidates
    )


def _remove_candidate(
    ctx,
    pending_id: str
) -> None:
    candidates = _load_candidates(
        ctx
    )

    if pending_id in candidates:
        candidates.pop(
            pending_id,
            None
        )

        ctx.state.set(
            STATE_KEY,
            candidates
        )


def _matching_candidates(
    ctx,
    identity: Dict[str, str]
) -> List[Dict[str, Any]]:
    matches = []

    for candidate in _load_candidates(
        ctx
    ).values():

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

        session_id = (
            identity.get(
                "session_id"
            )
            or ""
        )

        if (
            session_id
            and
            candidate.get(
                "session_id"
            )
            and
            candidate.get(
                "session_id"
            )
            != session_id
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


# =========================================================
# Natural-language preapproval
# =========================================================

def _route_key(
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


def _load_preapprovals(
    ctx
) -> Dict[str, float]:
    raw = ctx.state.get(
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
        ctx.state.set(
            PREAPPROVAL_KEY,
            cleaned
        )

    return cleaned


def _set_preapproval(
    ctx,
    identity: Dict[str, str]
) -> None:
    data = _load_preapprovals(
        ctx
    )

    data[
        _route_key(
            identity
        )
    ] = time.time()

    ctx.state.set(
        PREAPPROVAL_KEY,
        data
    )


def _consume_preapproval(
    ctx,
    identity: Dict[str, str]
) -> bool:
    data = _load_preapprovals(
        ctx
    )

    key = _route_key(
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

    ctx.state.set(
        PREAPPROVAL_KEY,
        data
    )

    return (
        time.time()
        - float(stamped)
        <= PREAPPROVAL_TTL_SECONDS
    )


# =========================================================
# Apply / cancel
# =========================================================

def _apply_pending(
    ctx,
    pending_id: str
) -> Dict[str, Any]:
    pending_id = str(
        pending_id
        or ""
    ).strip()

    record = wa.get_pending(
        wa.SKILLS,
        pending_id
    )

    if record is None:
        _remove_candidate(
            ctx,
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

    result = _load_json_result(
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
                "Skill gagal disimpan.",
        }

    wa.discard_pending(
        wa.SKILLS,
        pending_id
    )

    _remove_candidate(
        ctx,
        pending_id
    )

    return {
        "success": True,
        "saved": True,

        "pending_id":
            pending_id,

        "skill_name":
            str(
                payload.get(
                    "name"
                )
                or ""
            ).strip(),

        "action":
            str(
                payload.get(
                    "action"
                )
                or ""
            ).strip(),

        "file_path":
            str(
                payload.get(
                    "file_path"
                )
                or ""
            ).strip(),

        "saved_content":
            _saved_content(
                record
            ),

        "gist":
            str(
                record.get(
                    "summary"
                )
                or ""
            ).strip(),

        "message": (
            "Skill berhasil disimpan. "
            "Pada jawaban final WAJIB sebutkan "
            "nama skill dan isi/rule/framework "
            "yang baru disimpan."
        ),
    }


def _cancel_pending(
    ctx,
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

        skill_name = str(
            payload.get(
                "name"
            )
            or ""
        ).strip()

    wa.discard_pending(
        wa.SKILLS,
        pending_id
    )

    _remove_candidate(
        ctx,
        pending_id
    )

    return {
        "success": True,
        "saved": False,
        "cancelled": True,
        "skill_name":
            skill_name,
        "message":
            "Update skill dibatalkan oleh user.",
    }


# =========================================================
# Gateway hook
#
# Handles typed:
#   update skill
#   simpan skill
#
# Also blocks native /skills commands from unauthorized IDs.
# =========================================================

def build_pre_gateway_dispatch(
    ctx
):
    def pre_gateway_dispatch(
        event,
        **kwargs
    ):
        identity = _event_identity(
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
        # Protect native Hermes /skills approval path.
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
                not _is_authorized(
                    ctx,
                    identity
                )
            ):
                return {
                    "action": "rewrite",
                    "text": (
                        "Permintaan perubahan atau approval skill "
                        "ditolak oleh policy Ardiles. "
                        "Telegram user ini tidak memiliki hak "
                        "update skill bersama. "
                        "Jangan mengubah, menyimpan, atau "
                        "menyetujui skill."
                    ),
                }

            return None

        # Only exact trigger phrases.
        if normalized not in TRIGGERS:
            return None

        # ---------------------------------------------
        # Unauthorized Telegram user
        # ---------------------------------------------

        if not _is_authorized(
            ctx,
            identity
        ):
            return {
                "action": "rewrite",
                "text": (
                    "Permintaan update skill ditolak "
                    "oleh policy Ardiles. "
                    "Telegram user ini tidak memiliki "
                    "hak update skill bersama. "
                    "Jangan memanggil skill_manage "
                    "dan jangan mengubah skill."
                ),
            }

        candidates = _matching_candidates(
            ctx,
            identity
        )

        # ---------------------------------------------
        # Exactly one staged update:
        # typed approval commits it immediately.
        # ---------------------------------------------

        if len(candidates) == 1:
            result = _apply_pending(
                ctx,
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
                    + "\nHuman memberi approval eksplisit "
                    "dengan trigger update skill/simpan skill. "
                    "Jangan panggil skill_manage lagi. "
                    "Balas dalam Bahasa Indonesia. "
                    "Jika saved=true, WAJIB konfirmasi "
                    "nama skill dan isi/rule/framework "
                    "yang benar-benar disimpan."
                ),
            }

        # ---------------------------------------------
        # More than one unresolved skill
        # ---------------------------------------------

        if len(candidates) > 1:
            return {
                "action": "rewrite",
                "text": (
                    "Ada lebih dari satu pengajuan "
                    "skill yang belum selesai untuk "
                    "percakapan ini. "
                    "Jangan approve apa pun. "
                    "Minta user menyebutkan skill "
                    "mana yang ingin disimpan."
                ),
            }

        # ---------------------------------------------
        # No staged update yet.
        #
        # The exact typed trigger itself becomes
        # pre-approval for the next skill_manage write
        # on this route for 3 minutes.
        # ---------------------------------------------

        _set_preapproval(
            ctx,
            identity
        )

        return {
            "action": "rewrite",
            "text": (
                "[ARDILES VERIFIED SKILL PRE-APPROVAL]\n"
                "Telegram user yang diotorisasi "
                "baru saja memberi approval eksplisit "
                "dengan trigger update skill/simpan skill. "
                "Tinjau konteks percakapan yang relevan "
                "dan buat/update skill menggunakan "
                "skill_manage. "
                "Jangan meminta approval kedua. "
                "Policy plugin akan menyimpan staged write "
                "secara otomatis pada turn ini. "
                "Setelah sukses, WAJIB sebutkan "
                "nama skill dan isi/rule/framework "
                "yang disimpan."
            ),
        }

    return pre_gateway_dispatch


# =========================================================
# Dynamic instruction for authorized Telegram turns
# =========================================================

def build_pre_llm_call(
    ctx
):
    def pre_llm_call(
        session_id="",
        user_message="",
        platform="",
        sender_id="",
        **kwargs
    ):
        identity = _session_identity()

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

        if not _is_authorized(
            ctx,
            identity
        ):
            return None

        return {
            "context": (
                "ARDILES SKILL UPDATE POLICY:\n"
                "- User Telegram ini berhak approve skill.\n"
                "- Jika skill_manage menghasilkan staged=true "
                "dan requires_human_confirmation=true, "
                "WAJIB segera panggil tool clarify.\n"
                "- Clarify harus menanyakan apakah learning "
                "akan disimpan, dengan choices persis: "
                "['Update Skill', 'Batal'].\n"
                "- Di Telegram choices tersebut akan tampil "
                "sebagai tombol.\n"
                "- Jangan mengatakan skill sudah tersimpan "
                "sebelum hasil setelah konfirmasi menunjukkan "
                "saved=true.\n"
                "- Setelah saved=true, jawaban final WAJIB "
                "menyebut nama skill dan menjelaskan "
                "isi/rule/framework yang benar-benar disimpan.\n"
                "- Jika user menulis persis 'update skill' "
                "atau 'simpan skill', itu adalah approval "
                "eksplisit. Ikuti instruksi verified "
                "pre-approval dari gateway dan jangan "
                "meminta approval kedua.\n"
                "- Jangan stage skill kedua sebelum "
                "pengajuan sebelumnya diselesaikan."
            )
        }

    return pre_llm_call


# =========================================================
# Transform tool results
#
# 1. Intercept skill_manage staged writes.
# 2. Enforce Telegram whitelist.
# 3. If typed preapproval exists -> save immediately.
# 4. Otherwise instruct model to show Telegram buttons.
# 5. Intercept clarify answer -> apply/cancel pending skill.
# =========================================================

def build_transform_tool_result(
    ctx
):
    def transform_tool_result(
        tool_name,
        args,
        result,
        session_id="",
        turn_id="",
        **kwargs
    ):
        # =================================================
        # SKILL_MANAGE
        # =================================================

        if tool_name == "skill_manage":
            parsed = _load_json_result(
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

            identity = _session_identity()

            if session_id:
                identity[
                    "session_id"
                ] = str(
                    session_id
                )

            # ---------------------------------------------
            # Unauthorized write attempt:
            # discard staged write immediately.
            # ---------------------------------------------

            if not _is_authorized(
                ctx,
                identity
            ):
                wa.discard_pending(
                    wa.SKILLS,
                    pending_id
                )

                _remove_candidate(
                    ctx,
                    pending_id
                )

                return json.dumps(
                    {
                        "success": False,
                        "saved": False,
                        "error":
                            "skill_update_not_authorized",
                        "message": (
                            "Skill update tidak disimpan. "
                            "Telegram user ini tidak memiliki "
                            "hak update skill bersama."
                        ),
                    },
                    ensure_ascii=False
                )

            # Remember which human/chat/session owns it.
            _save_candidate(
                ctx,
                pending_id,
                identity,
                turn_id=str(
                    turn_id
                    or ""
                ),
            )

            # ---------------------------------------------
            # Exact typed approval was already given.
            # Save without asking again.
            # ---------------------------------------------

            if _consume_preapproval(
                ctx,
                identity
            ):
                return json.dumps(
                    _apply_pending(
                        ctx,
                        pending_id
                    ),
                    ensure_ascii=False
                )

            record = wa.get_pending(
                wa.SKILLS,
                pending_id
            )

            skill_name = ""
            gist = ""

            if record:
                payload = (
                    record.get(
                        "payload"
                    )
                    or {}
                )

                skill_name = str(
                    payload.get(
                        "name"
                    )
                    or ""
                ).strip()

                gist = str(
                    record.get(
                        "summary"
                    )
                    or ""
                ).strip()

            # ---------------------------------------------
            # Not saved yet.
            # Model must call clarify -> Telegram buttons.
            # ---------------------------------------------

            return json.dumps(
                {
                    "success": True,
                    "staged": True,
                    "saved": False,
                    "pending_id":
                        pending_id,
                    "skill_name":
                        skill_name,
                    "gist":
                        gist,
                    "requires_human_confirmation":
                        True,
                    "message": (
                        "BELUM TERSIMPAN. "
                        "WAJIB panggil tool clarify sekarang. "
                        "Tanyakan apakah learning ini akan "
                        "disimpan ke skill, dengan choices "
                        "persis ['Update Skill', 'Batal']. "
                        "Jangan klaim sudah tersimpan."
                    ),
                },
                ensure_ascii=False
            )

        # =================================================
        # CLARIFY
        #
        # Telegram button answer comes back through
        # the built-in clarify result.
        # =================================================

        if tool_name == "clarify":
            parsed = _load_json_result(
                result
            )

            identity = _session_identity()

            if session_id:
                identity[
                    "session_id"
                ] = str(
                    session_id
                )

            if not _is_authorized(
                ctx,
                identity
            ):
                return None

            candidates = _matching_candidates(
                ctx,
                identity
            )

            if not candidates:
                return None

            # Only resolve the newest candidate.
            candidate = candidates[0]

            answer = ""
            question = ""
            choices = []

            # Batch clarify result.
            responses = parsed.get(
                "responses"
            )

            if (
                isinstance(
                    responses,
                    list
                )
                and
                responses
            ):
                first = (
                    responses[0]
                    if isinstance(
                        responses[0],
                        dict
                    )
                    else {}
                )

                answer = _normalize_text(
                    first.get(
                        "user_response"
                    )
                )

                question = _normalize_text(
                    first.get(
                        "question"
                    )
                )

                offered = first.get(
                    "choices_offered"
                )

                if isinstance(
                    offered,
                    list
                ):
                    choices = [
                        _normalize_text(
                            item
                        )
                        for item in offered
                    ]

            # Legacy single-question clarify result.
            elif "user_response" in parsed:
                answer = _normalize_text(
                    parsed.get(
                        "user_response"
                    )
                )

                question = _normalize_text(
                    parsed.get(
                        "question"
                    )
                )

                offered = parsed.get(
                    "choices_offered"
                )

                if isinstance(
                    offered,
                    list
                ):
                    choices = [
                        _normalize_text(
                            item
                        )
                        for item in offered
                    ]

            # Do not hijack unrelated clarify questions.
            approval_choices = (
                "update skill" in choices
                and
                "batal" in choices
            )

            skill_question = (
                "skill" in question
                or
                approval_choices
            )

            if not skill_question:
                return None

            pending_id = candidate[
                "pending_id"
            ]

            if answer == "update skill":
                return json.dumps(
                    _apply_pending(
                        ctx,
                        pending_id
                    ),
                    ensure_ascii=False
                )

            if answer == "batal":
                return json.dumps(
                    _cancel_pending(
                        ctx,
                        pending_id
                    ),
                    ensure_ascii=False
                )

            return None

        return None

    return transform_tool_result
