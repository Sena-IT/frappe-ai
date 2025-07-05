import frappe
import requests
import json
import os
import openai
from frappe_ai.api.mcp_client import list_mcp_tools, call_mcp_tool

def get_ai_settings():
    """Retrieves the AI Settings document once."""
    return frappe.get_single("AI Setting")

def get_openrouter_api_key(settings=None):
    """Retrieves the provisioned OpenRouter API key from AI Settings."""
    if settings is None:
        settings = get_ai_settings()
    if not settings.key_provisioned:
        raise frappe.PermissionError("OpenRouter API key has not been provisioned for this site.")
    return settings.get_password("site_api_key")

def get_openai_api_key(settings=None):
    """Retrieves the OpenAI API key from AI Settings."""
    if settings is None:
        settings = get_ai_settings()
    # This assumes a field 'openai_api_key' of type 'Password' exists in 'AI Setting' DocType.
    openai_key = settings.get_password("openai_api_key")
    if not openai_key:
        raise frappe.PermissionError("OpenAI API key is not set in AI Settings.")
    return openai_key

def get_mcp_server_url(settings=None):
    """Retrieves the MCP server URL from AI Settings."""
    if settings is None:
        settings = get_ai_settings()
    mcp_url = settings.get("mcp_server_url")
    if not mcp_url:
        raise frappe.ValidationError("MCP Server URL is not set in AI Settings.")
    return mcp_url

def openrouter_call(model_id: str, messages: list, tools: list = None, tool_choice: str = "auto", temperature: float = 0.2, settings=None):
    """
    Makes a call to the OpenRouter LLM API, supporting tool use.
    Returns the entire assistant message object from the response.
    """
    api_key = get_openrouter_api_key(settings)
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

def openai_responses_call(model_id: str, messages: list, log_container: list = None, settings=None):
    """
    Makes a call to the OpenAI Responses API, supporting tool use and conversation state.
    Returns the entire response object.
    """
    if settings is None:
        settings = get_ai_settings()
    
    client = openai.OpenAI(api_key=get_openai_api_key(settings))
    mcp_server_url = get_mcp_server_url(settings)
    
    tools_payload = [
            {
                "type": "mcp",
                "server_label": "sentrafrappe",
                "server_url": mcp_server_url,
                "require_approval": "never",
            },
        ]
    # The 'input' parameter expects the full message structure, not just the content string.
    input_payload = messages 
    instructions_payload = """ 
**Key Instructions:**
- **Follow Tool Schemas**: When calling a tool, you **must** use the exact parameter names defined in its function signature. Refer to the tool's definition to understand the required arguments and their format. Do not guess parameter names.
- **CRITICAL - Parameter Names**: For `create_document` and `update_document`, the parameter for the document's data is called `values`. The parameter `fields` is used for reading tools like `get_document`. **DO NOT** use `fields` when you mean to use `values`.
- **Pay Attention to Nested Objects**: Carefully examine every tool's schema for parameters that are of type 'object'. You **must** construct a nested JSON object for these parameters as specified in their schema. Do not flatten the structure. For example: `create_document(doctype='Contact', values={'first_name': 'John'})`.
- **Never Ask for Information**: You have tools to find information. Use them. Do not ask the user for names, IDs, or other details you can discover yourself.
- **Self-Correct on Errors**: If a tool returns an error, do not give up. This often means your initial assumption was wrong. Look at the error and try again to solve it with the tools that are available to you.
- **Do not ask for permission**: Do not ask the user for permission to use a tool. Recursively use the tools to find the answer and complete the task.
You can call multiple tools in the same run. Do not stop until the task is done. Keep iterating on what to do next given the situation and recursively call tools to solve tasks.
        """

    if log_container is not None:
        log_container.append({
            "step": "LLM Call",
            "status": "info",
            "data": {
                "model": model_id,
                "message_count": len(input_payload) if isinstance(input_payload, list) else 1
            }
        })

    response = client.responses.create(
        model=model_id,
        tools=tools_payload,
        input=input_payload,
        instructions=instructions_payload
    )
    return response

def llm_call(provider: str, model_id: str, messages: list, tools: list = None, tool_choice: str = "auto", temperature: float = 0.2, previous_response_id: str = None):
    # Get settings once and pass to the appropriate function
    settings = get_ai_settings()
    
    if provider == "openrouter":
        return openrouter_call(model_id, messages, tools, tool_choice, temperature, settings)
    else: # Default to openai
        return openai_responses_call(model_id, messages, settings=settings)

def format_openai_output_to_log(response_obj):
    """Formats the OpenAI response object into a structured log for the frontend."""
    log = []
    final_response_text = ""
    
    if not hasattr(response_obj, 'output') or not response_obj.output:
        return log, final_response_text

    for item in response_obj.output:
        item_dict = item.model_dump(exclude_unset=True)
        step_name = item_dict.get('type', 'Unknown Step').replace('_', ' ').title()
        status = 'success'
        data = {}

        if item_dict.get('error'):
            status = 'error'
            data['error'] = item_dict['error']
        
        if item_dict.get('type') == 'mcp_list_tools':
            step_name = f"List Tools ({item_dict.get('server_label', '')})"
            tools_list = item_dict.get('tools', [])
            data['tools_found'] = len(tools_list)
            # Log only tool names, not full schemas
            data['tool_names'] = [tool.get('name', 'unknown') for tool in tools_list] if tools_list else []

        elif item_dict.get('type') == 'mcp_call':
            tool_name = item_dict.get('name', 'unknown_tool')
            step_name = f"Execute Tool: {tool_name}"
            data['tool_name'] = tool_name
            # Log summary instead of full arguments and output
            if item_dict.get('arguments'):
                data['arguments_provided'] = True
                data['arg_count'] = len(item_dict.get('arguments', {}))
            if item_dict.get('output'):
                output = item_dict.get('output')
                data['output_received'] = True
                # Summarize output instead of logging everything
                if isinstance(output, str):
                    data['output_size'] = len(output)
                elif isinstance(output, (list, dict)):
                    data['output_type'] = type(output).__name__
                    data['output_size'] = len(str(output)) if output else 0

        elif item_dict.get('type') == 'message':
            step_name = "Assistant Message"
            if item_dict.get('role') == 'assistant' and item_dict.get('content'):
                text_content = ""
                for content_part in item_dict['content']:
                    if content_part.get('type') == 'output_text':
                        text_content += content_part.get('text', '')
                # Don't add empty messages to the final response
                if text_content.strip():
                    final_response_text += text_content + "\\n\\n"
                # Skip adding empty assistant messages to the log
                if not text_content.strip():
                    continue
                # Log message length instead of full content for brevity
                data['message_length'] = len(text_content)
                data['has_content'] = True
                # Only log first 100 chars for debugging if needed
                data['preview'] = text_content[:100] + "..." if len(text_content) > 100 else text_content
            else:
                # Don't log non-assistant messages
                continue
        
        log.append({"step": step_name, "status": status, "data": data})

    return log, final_response_text.strip()

@frappe.whitelist()
def run_tool_orchestration(user_query: str):
    """
    Runs a multi-step tool-use loop, allowing the LLM to recursively use tools
    from the MCP server to answer a user's query.
    """
    try:
        # Get settings once for the entire orchestration
        settings = get_ai_settings()
        
        messages = [{"role": "user", "content": user_query}]
        initial_log = []
        response_obj = openai_responses_call("gpt-4.1", messages, log_container=initial_log, settings=settings)
        
        parsed_log, final_response = format_openai_output_to_log(response_obj)

        log = initial_log + parsed_log
        
        has_error = any(step['status'] == 'error' for step in log)

        # Add completion summary
        tool_calls = len([step for step in log if step['step'].startswith('Execute Tool:')])
        log.append({
            "step": "Orchestration Complete",
            "status": "success" if not has_error else "completed_with_errors",
            "data": {
                "total_steps": len(log),
                "tool_calls": tool_calls,
                "final_response": final_response
            }
        })

        # If the final response is empty but there's no error, use a default message
        if not final_response and not has_error:
            final_response = "The process completed, but no final answer was generated."

        return {"log": log, "final_response": final_response, "error": has_error}
    except Exception as e:
        frappe.log_error(f"Tool Orchestration Failed: {str(e)}", "Tool Orchestration")
        return {
            "log": [{
                "step": "Orchestration Failed",
                "status": "error",
                "data": {"error": str(e)}
            }],
            "final_response": f"**Orchestration Failed**\n\nAn unhandled error occurred: {str(e)}",
            "error": True
        } 