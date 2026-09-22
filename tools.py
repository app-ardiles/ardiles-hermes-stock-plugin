import json
import urllib.parse
import urllib.request

def search_stock_item(args, api_url):
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps({"success": False, "error": "query is required"}, ensure_ascii=False)

    api_url = str(api_url or "").strip()
    if not api_url:
        return json.dumps({"success": False, "error": "Ardiles Stock API URL is not configured"}, ensure_ascii=False)

    separator = "&" if "?" in api_url else "?"
    url = f"{api_url}{separator}{urllib.parse.urlencode({'q': query})}"

    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "Hermes-Ardiles-Stock/0.1"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        return json.dumps(data, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {"success": False, "error": "stock_api_request_failed", "detail": str(exc)},
            ensure_ascii=False,
        )
