SEARCH_STOCK_ITEM = {
    "name": "search_stock_item",
    "description": (
        "Identify the intended Ardiles stock model family from the user's wording. "
        "Pass the user's wording as written; do not silently correct it before calling. "
        "Results may contain direct or typo-tolerant candidates. "
        "Use this first when the exact product/model is not yet known."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "User's product/model wording exactly as provided."
            }
        },
        "required": ["query"]
    }
}

GET_MODEL_VARIANTS = {
    "name": "get_model_variants",
    "description": (
        "Get all known sizes, colors, stock quantities, and locations for one confirmed base model. "
        "Use after identifying a base model, or when the user asks what variants exist."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "base_model": {
                "type": "string",
                "description": "Exact base model, e.g. PRG-DRIVE XTEND."
            }
        },
        "required": ["base_model"]
    }
}

GET_STOCK_DETAIL = {
    "name": "get_stock_detail",
    "description": (
        "Get complete stock facts for one exact confirmed BARANG, including total quantity, "
        "snapshot date, location breakdown, and ACCSYS breakdown."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "barang": {
                "type": "string",
                "description": "Exact BARANG name."
            }
        },
        "required": ["barang"]
    }
}

GET_STOCK_BY_LOCATION = {
    "name": "get_stock_by_location",
    "description": (
        "Get stock for one exact BARANG filtered to a warehouse/location, including ACCSYS breakdown."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "barang": {
                "type": "string",
                "description": "Exact BARANG name."
            },
            "lokasi": {
                "type": "string",
                "description": "Location or warehouse wording, e.g. GD. 20 BARU."
            }
        },
        "required": ["barang", "lokasi"]
    }
}

GET_STOCK_BY_ACCSYS = {
    "name": "get_stock_by_accsys",
    "description": (
        "Get stock for one exact BARANG filtered by ACCSYS, including breakdown by location."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "barang": {
                "type": "string",
                "description": "Exact BARANG name."
            },
            "accsys": {
                "type": "string",
                "description": "ACCSYS value or wording, e.g. PAJAK."
            }
        },
        "required": ["barang", "accsys"]
    }
}

GET_LOCATION_SUMMARY = {
    "name": "get_location_summary",
    "description": (
        "Summarize a stock location/warehouse: total stock quantity, unique items, "
        "matched locations, and top stocked items."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "lokasi": {
                "type": "string",
                "description": "Location or warehouse wording."
            }
        },
        "required": ["lokasi"]
    }
}

GET_STOCK_DATA_STATUS = {
    "name": "get_stock_data_status",
    "description": (
        "Return the current published stock dataset status: snapshot date, batch, file, "
        "row counts, total quantity, unique items, and unique locations. "
        "Use when the user asks how current the stock data is or what dataset is active."
    ),
    "parameters": {
        "type": "object",
        "properties": {}
    }
}
