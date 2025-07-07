# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

import frappe
import json
from frappe.model.document import Document
from frappe.utils import now_datetime
from frappe_ai.api.tool_orchestrator import openai_responses_call

class SalesConversation(Document):
	pass

def process_message(docname: str, user_message: str):
	"""
	This is the background job that processes the user's message,
	calls the LLM, and sends a reply.
	"""
	print(f"--- BACKGROUND JOB: STARTED for doc {docname} ---")
	doc = frappe.get_doc("Sales Conversation", docname)
	try:
		history = json.loads(doc.conversation_history) if doc.conversation_history else []
	except (json.JSONDecodeError, TypeError):
		history = []
	history.append({"role": "user", "content": user_message})
	
	try:
		print(f"--- BACKGROUND JOB: Step 1: Calling LLM for doc {doc.name} ---")
		llm_response_obj = openai_responses_call(
			model_id="gpt-4.1", # Corrected model ID from user
			messages=history
		)
		print(f"--- BACKGROUND JOB: Step 2: LLM call successful for doc {doc.name} ---")

		# Correctly parse the response object to get the message content
		bot_reply_text = ""
		if hasattr(llm_response_obj, 'output') and llm_response_obj.output:
			for item in llm_response_obj.output:
				if hasattr(item, 'type') and item.type == 'message' and hasattr(item, 'role') and item.role == 'assistant':
					if hasattr(item, 'content') and isinstance(item.content, list):
						for content_part in item.content:
							if hasattr(content_part, 'type') and content_part.type == 'output_text':
								bot_reply_text += content_part.text
					# If we found text, we can stop processing this item
					if bot_reply_text:
						break
		
		if not bot_reply_text:
			bot_reply_text = "Sorry, I encountered an issue and cannot respond at the moment."
			print(f"--- BACKGROUND JOB: WARNING: LLM response did not contain message content for {doc.name} ---")
			frappe.log_error("Sales Bot: LLM response did not contain assistant message content.", llm_response_obj.model_dump_json(indent=2))

		print(f"--- BACKGROUND JOB: Step 3: Saving conversation history for doc {doc.name} ---")
		history.append({"role": "assistant", "content": bot_reply_text})
		doc.conversation_history = json.dumps(history, indent=4)
		doc.last_interaction = now_datetime()
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		print(f"--- BACKGROUND JOB: Step 4: Document saved successfully for doc {doc.name} ---")

		# Send the reply using the official frappe_whatsapp function
		print(f"--- BACKGROUND JOB: Step 5: Sending reply to {doc.customer_identifier} ---")
		frappe.call(
			"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.send_whatsapp_message",
			to=doc.customer_identifier,
			message=bot_reply_text,
			reference_doctype="Sales Conversation",
			reference_name=doc.name
		)
		print(f"--- BACKGROUND JOB: FINISHED doc {doc.name} ---")

	except Exception as e:
		# This will print the exact error to the console
		print(f"--- BACKGROUND JOB: CRITICAL ERROR for doc {doc.name}: {e} ---")
		frappe.log_error(f"Sales Bot: Error during LLM call or processing. Error: {e}", doc.name)
		error_message = "I'm sorry, I'm having trouble connecting to my brain right now. Please try again in a moment."
		frappe.call(
			"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.send_whatsapp_message",
			to=doc.customer_identifier,
			message=error_message
		)

@frappe.whitelist()
def ingest_message(channel: str, customer_identifier: str, user_message: str):
	try:
		doc_name = frappe.db.exists(
			"Sales Conversation", {"customer_identifier": customer_identifier, "status": "Ongoing"}
		)

		if not doc_name:
			doc = frappe.new_doc("Sales Conversation")
			doc.channel = channel
			doc.customer_identifier = customer_identifier
			doc.insert(ignore_permissions=True)
			doc_name = doc.name
		
		# Correct enqueue path
		frappe.enqueue(
			"frappe_ai.frappe_ai.doctype.sales_conversation.sales_conversation.process_message",
			queue="short",
			docname=doc_name,
			user_message=user_message
		)
		
		return {"status": "success", "message": "Message enqueued for processing."}
	
	except Exception as e:
		frappe.log_error("ingest_message: CRITICAL ERROR", str(e))
		raise 