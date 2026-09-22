SEARCH_STOCK_ITEM = {
    "name": "search_stock_item",
    "description": (
        "Search Ardiles published stock data by product/model text. "
        "Use this whenever the user asks to find a stock item, model, or product by name. "
        "The result includes the stock snapshot date, matching products, total quantity, "
        "and number of locations. Always treat snapshot_date as the data date."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Product or model search text, for example CRESCENDO."
            }
        },
        "required": ["query"]
    }
}
