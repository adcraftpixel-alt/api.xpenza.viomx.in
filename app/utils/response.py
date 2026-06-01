from typing import Any, List, Optional


def success(data: Any, message: str = "Success", meta: Optional[dict] = None) -> dict:
    response = {"success": True, "message": message, "data": data}
    if meta:
        response["meta"] = meta
    return response


def error(message: str, errors: List[Any] = []) -> dict:
    return {"success": False, "message": message, "errors": errors}
