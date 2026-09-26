import json

from .tools import _safe_call


QUERY_ARDILES_DATA = {
    "name": "query_ardiles_data",
    "description": (
        "Run a flexible READ-ONLY PostgreSQL query against Ardiles processed business data. "
        "For the current Stock AI pilot, access is limited to the ardiles_stock_history "
        "schema plus information_schema for schema discovery. "

        "Use this tool when the user's question cannot be answered efficiently by the existing "
        "stock tools, when custom grouping, aggregation, join, ranking, drill-down, or historical "
        "analysis is required, or when available tables and columns must be inspected first. "

        "IMPORTANT STOCK-HISTORY SEMANTICS: Ardiles Stock History is version based. "
        "A stock condition for a requested date must represent the EFFECTIVE STATE as of that date, "
        "not merely the rows physically present in that date's import batch. "
        "Rows classified UNCHANGED may not create a new stock version because their previous "
        "version remains valid. Therefore absence of a row from the latest batch does NOT by itself "
        "mean that stock is missing, partial, or unavailable. "

        "For as-of stock analysis, use only data originating from PUBLISHED batches and reconstruct "
        "the latest applicable versions up to the requested date. "
        "stock_versions supplies stock quantity and price state by product/location/accsys; "
        "product_versions supplies product metadata such as barang, model, division, supplier and "
        "factory PIC; product_accsys_versions supplies function state; location_versions supplies "
        "location state valid for the requested date. "

        "If exact table names, columns, or relationships are uncertain, inspect information_schema "
        "before composing the business query instead of guessing. "

        "Do NOT describe a snapshot as partial, incomplete, or only part of the data merely because "
        "unchanged values are carried forward from earlier effective versions. "
        "Do NOT add a default coverage warning. Mention warehouse/location coverage only when the "
        "user asks about it, when it materially affects the requested analysis, or when database "
        "evidence actually shows a coverage difference or missing data. "

        "Answer using quantities and facts supported by the effective database state. "
        "Do not infer causes of stock increases or decreases such as purchases, receipts, sales, "
        "returns, or transfers unless another trusted data source proves the cause. "

        "Only send a single SELECT or WITH ... SELECT statement and do not include a semicolon. "
        "Never attempt INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, or any other write/admin action."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "One PostgreSQL read-only SELECT or WITH ... SELECT statement. "
                    "Do not include a trailing semicolon."
                )
            },
            "params": {
                "type": "array",
                "description": (
                    "Optional positional parameter values corresponding to "
                    "$1, $2, and so on in the SQL query."
                ),
                "items": {}
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5000,
                "description": (
                    "Maximum rows to return. Defaults to 1000 and is capped at 5000."
                )
            }
        },
        "required": ["sql"]
    }
}


def query_ardiles_data(
    args,
    base_api_url,
    api_key=""
):
    sql = str(
        args.get("sql", "")
    ).strip()

    if not sql:
        return json.dumps(
            {
                "success": False,
                "error": "sql is required"
            },
            ensure_ascii=False
        )

    params = args.get(
        "params",
        []
    )

    if not isinstance(params, list):
        return json.dumps(
            {
                "success": False,
                "error": "params must be an array"
            },
            ensure_ascii=False
        )

    limit = args.get(
        "limit",
        1000
    )

    return _safe_call(
        base_api_url,
        "/api/ai/query",
        api_key=api_key,
        method="POST",
        payload={
            "sql": sql,
            "params": params,
            "limit": limit,
        },
    )
