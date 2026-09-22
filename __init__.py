from .schemas import SEARCH_STOCK_ITEM
from .tools import search_stock_item

def register(ctx):
    ctx.register_tool(
        name="search_stock_item",
        toolset="ardiles_stock",
        schema=SEARCH_STOCK_ITEM,
        handler=lambda args, **kwargs: search_stock_item(
            args,
            ctx.get_config("api_url", default=""),
        ),
    )
