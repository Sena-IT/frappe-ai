import click
import frappe
import signal
from frappe.commands import pass_context
from frappe.utils import get_sites

@click.command("mcp-dev-server", help="Run MCP server in foreground for development.")
@pass_context
def mcp_dev_server(context):
    from frappe_ai.api.tasks import get_mcp_server_settings, start_new_mcp_process, stop_all_mcp_processes

    sites = getattr(context, "sites", None) or get_sites()
    if not sites:
        click.secho("No sites found in this bench.", fg="red")
        return
    
    site = sites[0]
    if len(sites) > 1:
        click.secho(f"Multiple sites found. Using '{site}' for MCP server.", fg="yellow")

    frappe.init(site)
    frappe.connect()

    process = None

    def signal_handler(sig, frame):
        click.secho(f'\\nSignal {sig} received. Terminating MCP server...', fg="yellow")
        if process and process.poll() is None:
            process.terminate()
        # The `finally` block will handle DB cleanup and frappe.destroy()
        # Exiting here is important to stop the process.wait()
        exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        settings = get_mcp_server_settings()
        if not settings:
            click.secho(f"MCP Server is not enabled in AI Settings for site '{site}'. Exiting.", fg="yellow")
            return

        click.secho("Cleaning up any old MCP server processes...", fg="cyan")
        stop_all_mcp_processes()

        click.secho("Starting new MCP server process...", fg="cyan")
        process = start_new_mcp_process(settings)

        if not process:
            click.secho("Failed to start MCP server process. Check logs for details.", fg="red")
            return

        click.secho(f"MCP server started with PID: {process.pid}. Press Ctrl+C to stop.", fg="green")

        process.wait()
        click.secho("MCP server process has stopped.", fg="yellow")

    finally:
        # This block ensures that even on exception, we clean up.
        # It's also reached after process.wait() completes.
        if process and process.pid:
            running_doc = frappe.db.get_value("MCP Server Process", {"pid": process.pid, "status": "Running"})
            if running_doc:
                frappe.db.set_value("MCP Server Process", running_doc, "status", "Stopped")
                frappe.db.set_value("MCP Server Process", running_doc, "stopped_on", frappe.utils.now_datetime())
                frappe.db.commit()
        
        frappe.destroy()

commands = [
    mcp_dev_server
] 