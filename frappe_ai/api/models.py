import frappe
import requests

CURATED_MODELS = [
    {
        "id": "google/gemini-2.5-pro",
        "name": "Google Gemini 2.5 Pro",
        "provider": "Google"
    },
    {
        "id": "google/gemini-2.5-flash",
        "name": "Google Gemini 2.5 Flash",
        "provider": "Google"
    },
    {
        "id": "anthropic/claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "provider": "Anthropic"
    },
    {
        "id": "anthropic/claude-3.7-sonnet",
        "name": "Claude 3.7 Sonnet",
        "provider": "Anthropic"
    },
    {
        "id": "openai/o3",
        "name": "OpenAI O3",
        "provider": "OpenAI"
    },
    {
        "id": "openai/gpt-4.1",
        "name": "OpenAI GPT-4.1",
        "provider": "OpenAI"
    }
]

@frappe.whitelist()
def get_curated_models():
    """
    A simple function that returns the hardcoded list of models.
    """
    return CURATED_MODELS

@frappe.whitelist()
def run_model_test(model_id: str):
    """
    Sends a test message to a specific model using the site's API key.
    """
    settings = frappe.get_single("AI Setting")

    if not settings.key_provisioned:
        frappe.throw("API key has not been provisioned for this site.")
    
    prompt = "Tell me the funniest joke you can think of"
        
    api_key = settings.site_api_key

    try:
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        print("headers===",headers)
        body = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "reasoning": {
                "exclude": True
            }
        }
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=body
        )
        response.raise_for_status()
        response_data = response.json()
        
        return {"response": response_data["choices"][0]["message"]["content"]}

    except requests.exceptions.RequestException as e:
        frappe.log_error(f"Test API call failed: {e.response.text if e.response else e}")
        if e.response and e.response.status_code == 401:
            frappe.throw(
                "The provided API Key is invalid or has been rejected. Please verify your key and try again.",
                title="Authorization Failed"
            )
        frappe.throw(f"Test API call failed for model {model_id}. Check logs for details.")
