import frappe
import requests
import json
from frappe_ai.api.mcp_client import list_mcp_tools, call_mcp_tool

def get_openrouter_api_key():
    """Retrieves the provisioned OpenRouter API key from AI Settings."""
    settings = frappe.get_single("AI Setting")
    if not settings.key_provisioned:
        raise frappe.PermissionError("OpenRouter API key has not been provisioned for this site.")
    return settings.get_password("site_api_key")

def llm_call(model_id: str, messages: list, tools: list = None, tool_choice: str = "auto", temperature: float = 0.2):
    """
    Makes a call to the LLM API, supporting tool use.
    Returns the entire assistant message object from the response.
    """
    api_key = get_openrouter_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    body = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = tool_choice
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=180 # Increased timeout for potentially long tool-use chains
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]
    except requests.exceptions.RequestException as e:
        frappe.log_error(f"LLM call failed: {e.response.text if e.response else e}", "LLM Call Error")
        raise

@frappe.whitelist()
def run_tool_orchestration(user_query: str):
    """
    Runs a multi-step tool-use loop, allowing the LLM to recursively use tools
    from the MCP server to answer a user's query.
    """
    log = []
    def add_log_step(step_name, status, data):
        log.append({"step": step_name, "status": status, "data": data})

    try:
        # 1. Get available tools from the MCP server to include in the system prompt
        add_log_step("List Available Tools", "running", {})
        mcp_tools_response = list_mcp_tools()
        available_tools_raw = mcp_tools_response.get("result", {}).get("tools", [])
        if not available_tools_raw or mcp_tools_response.get("error"):
            raise Exception(f"Failed to list MCP tools: {mcp_tools_response.get('error', 'No tools found')}")

        # Format for both the LLM API call and for the system prompt
        formatted_tools = [{"type": "function", "function": tool} for tool in available_tools_raw]
        tool_descriptions = "\n".join(
            f"- `{tool['name']}`: {tool['description']}" for tool in available_tools_raw
        )
        add_log_step("List Available Tools", "success", {"count": len(formatted_tools), "tools": formatted_tools})

        # 2. Create the system prompt and few-shot example to teach the agent how to think.
        system_prompt = f"""
You are a specialized AI assistant for a Frappe-powered system. Your mission is to complete user tasks by autonomously using tools.

**Available Tools**:
You have access to the following tools. Use them to complete the user's request.
{tool_descriptions}



**Key Instructions:**
- **Never Ask for Information**: You have tools to find information. Use them. Do not ask the user for names, IDs, or other details you can discover yourself.
- **Self-Correct on Errors**: If a tool returns an error, do not give up. This often means your initial assumption was wrong. Look at the error and try again to solve it with the tools that are available to you.
- **Do not ask for permission**: Do not ask the user for permission to use a tool. Recursively use the tools to find the answer and complete the task.
You can call multiple tools in the same run. Do not stop until the task is done. Keep iterating on what to do next given the situation and recursively call tools to solve tasks.
""" # TODO: Add a few-shot example to teach the agent how to think.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]
        max_turns = 10

        for i in range(max_turns):
            add_log_step(f"LLM Call (Turn {i+1})", "running", {"messages_sent": messages})
            
            assistant_message = llm_call(
                model_id="openai/gpt-4o",
                messages=messages,
                tools=formatted_tools
            )
            messages.append(assistant_message)
            add_log_step(f"LLM Call (Turn {i+1})", "success", {"assistant_response": assistant_message})

            if not assistant_message.get("tool_calls"):
                final_response = assistant_message.get("content", "I was unable to produce a final answer.")
                add_log_step("Orchestration Complete", "success", {"final_response": final_response})
                return {"log": log, "final_response": final_response}

            tool_calls = assistant_message["tool_calls"]
            tool_results = []
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]
                tool_call_id = tool_call["id"]
                
                add_log_step(f"Execute Tool: {tool_name}", "running", {"args": tool_args_str})
                try:
                    tool_args = json.loads(tool_args_str)
                    tool_result_response = call_mcp_tool(tool_name, tool_args)
                    
                    if tool_result_response.get("error"):
                        raise Exception(json.dumps(tool_result_response["error"]))
                    
                    result_content = tool_result_response.get("result", {})
                    add_log_step(f"Execute Tool: {tool_name}", "success", {"result": result_content})
                    tool_results.append({
                        "role": "tool", "tool_call_id": tool_call_id, "name": tool_name,
                        "content": json.dumps(result_content),
                    })
                except Exception as e:
                    error_msg = str(e)
                    add_log_step(f"Execute Tool: {tool_name}", "error", {"error": error_msg})
                    tool_results.append({
                        "role": "tool", "tool_call_id": tool_call_id, "name": tool_name,
                        "content": json.dumps({"error": error_msg, "details": "The tool failed to execute or returned an error."}),
                    })
            
            messages.extend(tool_results)

        final_response = "The process required too many steps to complete. The task has been halted."
        add_log_step("Orchestration Halted", "error", {"reason": "Max turns reached"})
        return {"log": log, "final_response": final_response, "error": True}

    except Exception as e:
        error_message = str(e)
        frappe.log_error(f"Tool Orchestration Failed: {error_message}", "Tool Orchestration")
        
        if log and log[-1]["status"] == "running":
            log[-1]["status"] = "error"
            log[-1]["data"]["error"] = error_message
        
        final_response = f"**Orchestration Failed**\n\nAn error occurred: {error_message}"
        return {"log": log, "final_response": final_response, "error": True} 