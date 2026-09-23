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


# Stock AI v2 flexible domain tools
_FILTERS = {
    "type": "object",
    "properties": {
        "q": {"type": "string"},
        "article": {"type": "string"},
        "model": {"type": "string"},
        "location": {"type": "string"},
        "accsys": {"type": "string"},
        "division": {"type": "string"},
        "function": {"type": "string"},
        "supplier": {"type": "string"},
        "qty_lt": {"type": "number"},
        "qty_lte": {"type": "number"},
        "qty_gt": {"type": "number"},
        "qty_gte": {"type": "number"},
        "cost_price_min": {"type": "number"},
        "cost_price_max": {"type": "number"},
        "selling_price_min": {"type": "number"},
        "selling_price_max": {"type": "number"},
        "cost_value_lt": {"type": "number"},
        "cost_value_gt": {"type": "number"},
        "retail_value_lt": {"type": "number"},
        "retail_value_gt": {"type": "number"},
        "zero_stock": {"type": "boolean"},
        "positive_stock": {"type": "boolean"}
    }
}

_GROUPS = ["article", "model", "location", "accsys", "division", "function", "supplier"]
_METRICS = [
    "qty", "article_count", "model_count", "location_count", "accsys_count",
    "cost_value", "retail_value", "potential_gross_profit",
    "missing_cost_rows", "missing_selling_price_rows",
    "missing_cost_qty", "missing_selling_price_qty",
    "min_cost_price", "max_cost_price", "min_selling_price", "max_selling_price"
]

STOCK_QUERY = {
    "name": "stock_query",
    "description": "Flexible read-only stock query for lists, filtering, low/zero stock, drill-down and pagination.",
    "parameters": {
        "type": "object",
        "properties": {
            "filters": _FILTERS,
            "group_by": {"type": "array", "items": {"type": "string", "enum": _GROUPS}},
            "metrics": {"type": "array", "items": {"type": "string", "enum": _METRICS}},
            "sort_by": {"type": "string"},
            "sort_direction": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": "string"},
            "snapshot": {"type": "string"}
        }
    }
}

STOCK_SUMMARY = {
    "name": "stock_summary",
    "description": "Aggregate stock totals and counts, optionally grouped by a business dimension.",
    "parameters": {
        "type": "object",
        "properties": {
            "filters": _FILTERS,
            "group_by": {"type": "array", "items": {"type": "string", "enum": _GROUPS}},
            "metrics": {"type": "array", "items": {"type": "string", "enum": _METRICS}},
            "sort_by": {"type": "string"},
            "sort_direction": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": "string"},
            "snapshot": {"type": "string"}
        }
    }
}

STOCK_VALUATION = {
    "name": "stock_valuation",
    "description": "Calculate inventory modal/HPP value, selling-price value, potential gross profit, and missing price coverage.",
    "parameters": {
        "type": "object",
        "properties": {
            "filters": _FILTERS,
            "group_by": {"type": "array", "items": {"type": "string", "enum": _GROUPS}},
            "basis": {"type": "string", "enum": ["cost", "retail", "both"]},
            "sort_by": {"type": "string"},
            "sort_direction": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": "string"},
            "snapshot": {"type": "string"}
        }
    }
}

STOCK_RANK = {
    "name": "stock_rank",
    "description": "Rank stock groups by quantity, modal value, retail value, or potential gross profit.",
    "parameters": {
        "type": "object",
        "properties": {
            "filters": _FILTERS,
            "group_by": {"type": "string", "enum": _GROUPS},
            "metric": {"type": "string", "enum": ["qty", "cost_value", "retail_value", "potential_gross_profit"]},
            "direction": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "cursor": {"type": "string"},
            "snapshot": {"type": "string"}
        },
        "required": ["group_by", "metric"]
    }
}

STOCK_COMPARE = {
    "name": "stock_compare",
    "description": "Compare the latest two published stock snapshots, or two requested snapshot dates.",
    "parameters": {
        "type": "object",
        "properties": {
            "from_snapshot": {"type": "string"},
            "to_snapshot": {"type": "string"},
            "filters": _FILTERS,
            "group_by": {"type": "string", "enum": _GROUPS},
            "metric": {"type": "string", "enum": ["qty", "cost_value", "retail_value", "potential_gross_profit"]},
            "direction": {"type": "string", "enum": ["asc", "desc"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100}
        }
    }
}

STOCK_DATA_HEALTH = {
    "name": "stock_data_health",
    "description": "Check the active stock snapshot for missing HPP/selling prices, missing locations/articles, negative or zero quantities, and price consistency.",
    "parameters": {
        "type": "object",
        "properties": {
            "snapshot": {"type": "string"}
        }
    }
}
