# frappe_ai/api/tasks.py

import frappe
import subprocess
import os
import signal
from typing import Dict, Any, Optional
from frappe_ai.api.mcp_client import call_mcp_tool, list_mcp_tools


def get_mcp_server_settings() -> Optional[Dict[str, str]]:
    """
    Fetches and validates the MCP server settings from the AI Setting DocType.
    """
    try:
        settings = frappe.get_single("AI Setting")
        if not settings.enable_mcp_server:
            return None

        # Validate that all required fields are set
        required_fields = {
            "mcp_server_command": settings.mcp_server_command,
            "mcp_frappe_url": settings.mcp_frappe_url,
            "mcp_frappe_api_key": settings.mcp_frappe_api_key,
            "mcp_frappe_api_secret": settings.get_password("mcp_frappe_api_secret"),
        }

        for field, value in required_fields.items():
            if not value:
                frappe.log_error(f"MCP Watchdog: Setting '{field}' is missing in AI Settings.", "MCP Task")
                return None
        
        return required_fields

    except Exception as e:
        frappe.log_error(f"MCP Watchdog: Could not retrieve AI Settings: {e}", "MCP Task")
        return None

def is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is running.
    This works on Unix-like systems (Linux, macOS).
    """
    if not pid:
        return False
    try:
        # Sending signal 0 to a process checks if it exists without harming it.
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

def start_new_mcp_process(settings: Dict[str, str]):
    """
    Launches a new MCP server process and creates a log document for it.
    Returns the process object on success, None on failure.
    """
    # Prepare the environment variables
    env = os.environ.copy()
    env["FRAPPE_URL"] = settings["mcp_frappe_url"]
    env["FRAPPE_API_KEY"] = settings["mcp_frappe_api_key"]
    env["FRAPPE_API_SECRET"] = settings["mcp_frappe_api_secret"]
    
    log_file_path = frappe.get_site_path("logs", f"mcp_server_{frappe.utils.now_datetime().strftime('%Y-%m-%d_%H-%M-%S')}.log")

    try:
        command = settings["mcp_server_command"].split()
        with open(log_file_path, "w") as log_file:
            process = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                text=True,
                bufsize=1
            )

        # Create a new log document in our custom DocType
        log_doc = frappe.new_doc("MCP Server Process")
        log_doc.status = "Running"
        log_doc.pid = process.pid
        log_doc.command = settings["mcp_server_command"]
        log_doc.started_on = frappe.utils.now_datetime()
        log_doc.log_file = log_file_path
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        frappe.log_error(f"MCP Watchdog: Started new MCP server process with PID {process.pid}. Log: {log_file_path}", "MCP Task")
        return process

    except Exception as e:
        frappe.log_error(f"MCP Watchdog: Failed to start new MCP server process. Error: {e}", "MCP Task")
        return None

def stop_all_mcp_processes():
    """Stops all running MCP server processes logged in the database."""
    running_docs = frappe.get_all("MCP Server Process", filters={"status": "Running"}, fields=["name", "pid"])
    if not running_docs:
        return

    frappe.log_error(f"MCP Watchdog: Found {len(running_docs)} running process(es) in the database. Stopping them...", "MCP Task")
    for doc in running_docs:
        if doc.pid and is_process_running(doc.pid):
            try:
                os.kill(doc.pid, signal.SIGTERM)
            except OSError as e:
                frappe.log_error(f"MCP Watchdog: Could not stop process {doc.pid}: {e}", "MCP Task")

        # Mark as stopped regardless of whether it was running, to clean up the DB state
        frappe.db.set_value("MCP Server Process", doc.name, "status", "Stopped")
        frappe.db.set_value("MCP Server Process", doc.name, "stopped_on", frappe.utils.now_datetime())
    
    frappe.db.commit()


@frappe.whitelist()
def test_mcp_connection():
    """
    A whitelisted function to test the connection by calling the 'ping' tool.
    This provides an end-to-end test of the entire communication pipeline.
    """
    try:
        # Call the 'ping' tool, which requires no arguments
        response = call_mcp_tool(tool_name="ping", arguments={})

        # The actual result is nested in the response, let's simplify it
        result = response.get("result", {})
        return result

    except Exception as e:
        # If anything goes wrong, return a formatted error
        frappe.log_error(f"MCP connection test failed: {e}", "MCP Test")
        frappe.response["http_status_code"] = 500
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def list_mcp_tools_endpoint():
    """
    A whitelisted endpoint to fetch the list of available tools from the MCP server.
    """
    try:
        response = list_mcp_tools()
        return response.get("result", {})
    except Exception as e:
        frappe.log_error(f"MCP list tools failed: {e}", "MCP Test")
        frappe.response["http_status_code"] = 500
        return {"error": True, "message": str(e)}


@frappe.whitelist()
def check_and_manage_mcp_server():
    """
    The main watchdog function to be called by the scheduler.
    This should NOT run in developer mode, as the Procfile handles it.
    """
    if frappe.conf.get("developer_mode"):
        return

    settings = get_mcp_server_settings()

    # 1. Check if the feature is disabled in settings
    if not settings:
        # If disabled, find and stop any process marked as "Running"
        stop_all_mcp_processes()
        return

    # 2. If enabled, check for a running process in our logs
    running_doc = frappe.get_all("MCP Server Process", filters={"status": "Running"}, limit=1)
    
    if running_doc:
        doc = running_doc[0]
        pid = doc.get("pid")
        
        # 3. Verify if the logged process is actually still alive
        if is_process_running(pid):
            # Process is running and healthy. Do nothing.
            print("MCP server process is healthy.")
            return
        else:
            # The process crashed. Log it and prepare to start a new one.
            frappe.log_error(f"MCP Watchdog: Found dead process (PID: {pid}). Marking as Error.", "MCP Task")
            frappe.db.set_value("MCP Server Process", doc.name, "status", "Error")
            frappe.db.set_value("MCP Server Process", doc.name, "stopped_on", frappe.utils.now_datetime())
            frappe.db.commit()

    # 4. If we reached here, it means no process is running. Start one.
    start_new_mcp_process(settings)


@frappe.whitelist()
def test_mcp_resource_read():
    """
    Tests reading a resource from the MCP server using a URI.
    """
    try:
        # We will try to read the schema for the 'User' doctype as a resource
        uri_to_read = "schema://User"
        response = mcp_client.read_mcp_resource(uri=uri_to_read)

        # The actual result is nested inside result.contents[0]
        result = response.get("result", {})
        return result.get("contents", [{}])[0]

    except Exception as e:
        frappe.log_error(f"MCP resource test failed: {e}", "MCP Test")
        frappe.response["http_status_code"] = 500
        return {"error": True, "message": str(e)}