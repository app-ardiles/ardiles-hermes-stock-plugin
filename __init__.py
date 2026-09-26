from agent.secret_scope import get_secret

from .schemas import (
    SEARCH_STOCK_ITEM,
    GET_MODEL_VARIANTS,
    GET_STOCK_DETAIL,
    GET_STOCK_BY_LOCATION,
    GET_STOCK_BY_ACCSYS,
    GET_LOCATION_SUMMARY,
    GET_STOCK_DATA_STATUS,
    GET_STOCK_SNAPSHOTS,
    STOCK_QUERY,
    STOCK_SUMMARY,
    STOCK_VALUATION,
    STOCK_RANK,
    STOCK_COMPARE,
    STOCK_CHANGES,
    STOCK_DATA_HEALTH,
)

from .tools import (
    search_stock_item,
    get_model_variants,
    get_stock_detail,
    get_stock_by_location,
    get_stock_by_accsys,
    get_location_summary,
    get_stock_data_status,
    get_stock_snapshots,
    stock_query,
    stock_summary,
    stock_valuation,
    stock_rank,
    stock_compare,
    stock_changes,
    stock_data_health,
)

from .ai_query import (
    QUERY_ARDILES_DATA,
    query_ardiles_data,
)

from .skill_approval import (
    REQUEST_SKILL_APPROVAL,
    SkillApproval,
)


def register(ctx):
    def cfg(name, default=""):
        return ctx.get_config(
            name,
            default=default
        )

    def common():
        base_api_url = cfg(
            "base_api_url",
            ""
        )

        # Secure profile-scoped secret.
        # Required for Hermes shared/multiplex gateway.
        api_key = str(
            get_secret(
                "ARDILES_API_KEY",
                ""
            )
            or ""
        ).strip()

        # Legacy migration fallback only.
        if not api_key:
            api_key = str(
                cfg(
                    "api_key",
                    ""
                )
            ).strip()

        return (
            base_api_url,
            api_key,
        )

    # =====================================================
    # Ardiles Stock tools
    # =====================================================

    tools = [
        (
            "search_stock_item",
            SEARCH_STOCK_ITEM,
            search_stock_item
        ),

        (
            "get_model_variants",
            GET_MODEL_VARIANTS,
            get_model_variants
        ),

        (
            "get_stock_detail",
            GET_STOCK_DETAIL,
            get_stock_detail
        ),

        (
            "get_stock_by_location",
            GET_STOCK_BY_LOCATION,
            get_stock_by_location
        ),

        (
            "get_stock_by_accsys",
            GET_STOCK_BY_ACCSYS,
            get_stock_by_accsys
        ),

        (
            "get_location_summary",
            GET_LOCATION_SUMMARY,
            get_location_summary
        ),

        (
            "get_stock_data_status",
            GET_STOCK_DATA_STATUS,
            get_stock_data_status
        ),

        (
            "get_stock_snapshots",
            GET_STOCK_SNAPSHOTS,
            get_stock_snapshots
        ),

        (
            "stock_query",
            STOCK_QUERY,
            stock_query
        ),

        (
            "stock_summary",
            STOCK_SUMMARY,
            stock_summary
        ),

        (
            "stock_valuation",
            STOCK_VALUATION,
            stock_valuation
        ),

        (
            "stock_rank",
            STOCK_RANK,
            stock_rank
        ),

        (
            "stock_compare",
            STOCK_COMPARE,
            stock_compare
        ),

        (
            "stock_changes",
            STOCK_CHANGES,
            stock_changes
        ),

        (
            "stock_data_health",
            STOCK_DATA_HEALTH,
            stock_data_health
        ),

        (
            "query_ardiles_data",
            QUERY_ARDILES_DATA,
            query_ardiles_data
        ),
    ]

    for name, schema, handler in tools:
        ctx.register_tool(
            name=name,
            toolset="ardiles_stock",
            schema=schema,
            handler=lambda args, _handler=handler, **kwargs:
                _handler(
                    args,
                    *common()
                ),
        )

    # =====================================================
    # Secure Ardiles Skill Approval
    # =====================================================

    skill_approval = SkillApproval(
        ctx
    )

    # Tool called by Sekar AFTER skill_manage has passed
    # pre-validation.
    ctx.register_tool(
        name="request_skill_approval",
        toolset="ardiles_stock",
        schema=REQUEST_SKILL_APPROVAL,
        handler=skill_approval.request_skill_approval,
        is_async=True,
    )

    # Intercept Telegram messages such as:
    #   update skill
    #   simpan skill
    #
    # Also protects /skills from unauthorized Telegram IDs.
    ctx.register_hook(
        "pre_gateway_dispatch",
        skill_approval.pre_gateway_dispatch
    )

    # Inject Ardiles approval workflow instructions only
    # for authorized Telegram users.
    ctx.register_hook(
        "pre_llm_call",
        skill_approval.pre_llm_call
    )

    # Intercept staged skill_manage results:
    #
    # invalid payload
    #   -> reject before human approval
    #
    # valid payload
    #   -> expose request_skill_approval
    #
    # typed preapproval
    #   -> save immediately
    ctx.register_hook(
        "transform_tool_result",
        skill_approval.transform_tool_result
    )

    # Native Telegram inline buttons:
    #
    #   [ ✅ Update Skill ] [ ❌ Batal ]
    #
    # This intentionally does NOT use Hermes clarify,
    # therefore there is no "(Recommended)" label.
    ctx.register_telegram_handler(
        skill_approval.wire_telegram
    )
