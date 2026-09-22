from .schemas import (
    SEARCH_STOCK_ITEM,
    GET_MODEL_VARIANTS,
    GET_STOCK_DETAIL,
    GET_STOCK_BY_LOCATION,
    GET_STOCK_BY_ACCSYS,
    GET_LOCATION_SUMMARY,
    GET_STOCK_DATA_STATUS,
)

from .tools import (
    search_stock_item,
    get_model_variants,
    get_stock_detail,
    get_stock_by_location,
    get_stock_by_accsys,
    get_location_summary,
    get_stock_data_status,
)


def register(ctx):
    def cfg(name, default=""):
        return ctx.get_config(name, default=default)

    common = lambda: (
        cfg("base_api_url", ""),
        cfg("api_key", ""),
    )

    ctx.register_tool(
        name="search_stock_item",
        toolset="ardiles_stock",
        schema=SEARCH_STOCK_ITEM,
        handler=lambda args, **kwargs: search_stock_item(args, *common()),
    )

    ctx.register_tool(
        name="get_model_variants",
        toolset="ardiles_stock",
        schema=GET_MODEL_VARIANTS,
        handler=lambda args, **kwargs: get_model_variants(args, *common()),
    )

    ctx.register_tool(
        name="get_stock_detail",
        toolset="ardiles_stock",
        schema=GET_STOCK_DETAIL,
        handler=lambda args, **kwargs: get_stock_detail(args, *common()),
    )

    ctx.register_tool(
        name="get_stock_by_location",
        toolset="ardiles_stock",
        schema=GET_STOCK_BY_LOCATION,
        handler=lambda args, **kwargs: get_stock_by_location(args, *common()),
    )

    ctx.register_tool(
        name="get_stock_by_accsys",
        toolset="ardiles_stock",
        schema=GET_STOCK_BY_ACCSYS,
        handler=lambda args, **kwargs: get_stock_by_accsys(args, *common()),
    )

    ctx.register_tool(
        name="get_location_summary",
        toolset="ardiles_stock",
        schema=GET_LOCATION_SUMMARY,
        handler=lambda args, **kwargs: get_location_summary(args, *common()),
    )

    ctx.register_tool(
        name="get_stock_data_status",
        toolset="ardiles_stock",
        schema=GET_STOCK_DATA_STATUS,
        handler=lambda args, **kwargs: get_stock_data_status(args, *common()),
    )
