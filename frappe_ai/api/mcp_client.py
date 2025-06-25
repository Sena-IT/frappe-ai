# frappe_ai/api/mcp_client.py

import frappe
import requests
import json
import uuid

def _make_mcp_post_request(url: str, payload: dict, timeout: int) -> dict:
    """
    A helper function to make a precise, minimal HTTP POST request.
    """
    # Create a new session for each request to ensure no headers are reused.
    session = requests.Session()
    
    # Clear any default headers (like User-Agent, Accept-Encoding) from the session.
    session.headers.clear()

    # Set ONLY the headers the MCP server strictly requires.
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    })

    try:
        response = session.post(url, data=json.dumps(payload), timeout=timeout)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.Timeout:
        raise TimeoutError(f"Request to MCP server at {url} timed out.")
    except requests.exceptions.ConnectionError:
        raise ConnectionError(f"Connection refused by MCP server at {url}. Is it running?")
    except requests.exceptions.HTTPError as e:
        # Re-raise HTTP errors with a more specific message
        raise e.__class__(f"{e.response.status_code} Client Error: {e.response.reason} for url: {url}")
    except Exception as e:
        frappe.log_error(f"Error communicating with MCP server: {e}", "MCP Client")
        raise

def call_mcp_tool(tool_name: str, arguments: dict, timeout: int = 20) -> dict:
    """
    Connects to the running MCP server via HTTP and calls a tool.
    """
    try:
        settings = frappe.get_single("AI Setting")
        url = f"http://127.0.0.1:4000/mcp"
    except Exception:
        raise ConnectionError("Could not get MCP server port from AI Settings.")

    request_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
        "id": request_id,
    }

    frappe.log_error(f"MCP Test: Sending payload to MCP server: {payload}", "MCP Test")
    response_json = _make_mcp_post_request(url, payload, timeout)

    if response_json.get("id") != request_id:
        raise ConnectionError("Error: Received response with a mismatched ID.")
        
    return response_json

def list_mcp_tools(timeout: int = 20) -> dict:
    """
    Connects to the running MCP server via HTTP and lists available tools.
    """
    try:
        settings = frappe.get_single("AI Setting")
        url = f"http://127.0.0.1:4000/mcp"
    except Exception:
        raise ConnectionError("Could not get MCP server port from AI Settings.")

    request_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "params": {},
        "id": request_id,
    }

    response_json = _make_mcp_post_request(url, payload, timeout)

    if response_json.get("id") != request_id:
        raise ConnectionError("Error: Received response with a mismatched ID.")
        
    return response_json

def read_mcp_resource(uri: str, timeout: int = 20) -> dict:
    """
    Connects to the MCP server and reads a resource by its URI.
    """
    try:
        settings = frappe.get_single("AI Setting")
        url = f"http://127.0.0.1:4000/mcp"
    except Exception:
        raise ConnectionError("Could not get MCP server port from AI Settings.")

    request_id = str(uuid.uuid4())
    payload = {
        "jsonrpc": "2.0",
        "method": "resources/read",
        "params": {"uri": uri},
        "id": request_id,
    }

    frappe.log_error(f"MCP Test: Sending payload to MCP server: {payload}", "MCP Test")
    response_json = _make_mcp_post_request(url, payload, timeout)

    if response_json.get("id") != request_id:
        raise ConnectionError("Error: Received response with a mismatched ID.")
            
    return response_json