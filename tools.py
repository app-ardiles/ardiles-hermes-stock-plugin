import json
import urllib.parse
import urllib.request


def _request_json(base_api_url, path, params=None, api_key=""):
    base = str(base_api_url or "").strip().rstrip("/")
    if not base:
        return {
            "success": False,
            "error": "base_api_url_not_configured"
        }

    url = f"{base}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Accept": "application/json",
        "User-Agent": "Sekar-Ardiles-Stock/1.0",
    }

    key = str(api_key or "").strip()
    if key:
        headers["x-ardiles-api-key"] = key

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")

    if not body.strip():
        return {
            "success": False,
            "error": "empty_api_response"
        }

    return json.loads(body)


def _safe_call(base_api_url, path, params=None, api_key=""):
    try:
        return json.dumps(
            _request_json(base_api_url, path, params=params, api_key=api_key),
            ensure_ascii=False
        )
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "error": "ardiles_api_request_failed",
                "detail": str(exc),
            },
            ensure_ascii=False
        )


def search_stock_item(args, base_api_url, api_key=""):
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps(
            {"success": False, "error": "query is required"},
            ensure_ascii=False
        )

    return _safe_call(
        base_api_url,
        "/api/stock/search",
        {"q": query},
        api_key
    )


def get_model_variants(args, base_api_url, api_key=""):
    base_model = str(args.get("base_model", "")).strip()
    if not base_model:
        return json.dumps(
            {"success": False, "error": "base_model is required"},
            ensure_ascii=False
        )

    return _safe_call(
        base_api_url,
        "/api/stock/variants",
        {"base_model": base_model},
        api_key
    )


def get_stock_detail(args, base_api_url, api_key=""):
    barang = str(args.get("barang", "")).strip()
    if not barang:
        return json.dumps(
            {"success": False, "error": "barang is required"},
            ensure_ascii=False
        )

    return _safe_call(
        base_api_url,
        "/api/stock/detail",
        {"barang": barang},
        api_key
    )


def get_stock_by_location(args, base_api_url, api_key=""):
    barang = str(args.get("barang", "")).strip()
    lokasi = str(args.get("lokasi", "")).strip()

    if not barang or not lokasi:
        return json.dumps(
            {"success": False, "error": "barang and lokasi are required"},
            ensure_ascii=False
        )

    return _safe_call(
        base_api_url,
        "/api/stock/by-location",
        {"barang": barang, "lokasi": lokasi},
        api_key
    )


def get_stock_by_accsys(args, base_api_url, api_key=""):
    barang = str(args.get("barang", "")).strip()
    accsys = str(args.get("accsys", "")).strip()

    if not barang or not accsys:
        return json.dumps(
            {"success": False, "error": "barang and accsys are required"},
            ensure_ascii=False
        )

    return _safe_call(
        base_api_url,
        "/api/stock/by-accsys",
        {"barang": barang, "accsys": accsys},
        api_key
    )


def get_location_summary(args, base_api_url, api_key=""):
    lokasi = str(args.get("lokasi", "")).strip()

    if not lokasi:
        return json.dumps(
            {"success": False, "error": "lokasi is required"},
            ensure_ascii=False
        )

    return _safe_call(
        base_api_url,
        "/api/stock/location-summary",
        {"lokasi": lokasi},
        api_key
    )


def get_stock_data_status(args, base_api_url, api_key=""):
    return _safe_call(
        base_api_url,
        "/api/stock/status",
        None,
        api_key
    )
