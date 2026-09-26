import json

from .tools import _safe_call


QUERY_ARDILES_DATA = {
    "name": "query_ardiles_data",
    "description": (
        "Run a flexible READ-ONLY PostgreSQL query against Ardiles processed business data. "
        "For the current Stock AI pilot, access is limited to the ardiles_stock_history "
        "schema plus information_schema for schema discovery. "
        "Use this when the user's question cannot be answered efficiently by the existing "
        "stock tools, when custom grouping/aggregation/join/drill-down is required, or when "
        "you need to inspect available tables and columns before answering. "
        "Only send a single SELECT or WITH ... SELECT statement and do not include a semicolon. "
        "Never attempt INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, or any other write/admin action. "
        "If table or column names are uncertain, inspect information_schema first instead of guessing."
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
