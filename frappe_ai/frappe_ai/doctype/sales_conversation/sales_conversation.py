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
	The AI handles the complete conversation including sending the response.
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
		
		# Add system context to help AI understand what to do
		enhanced_messages = [
			{
				"role": "system", 
				"content": f"You are a professional sales assistant handling a {doc.channel} conversation with customer {doc.customer_identifier}. "
				f"IMPORTANT: Always respond in English language only."
				f"After responding to their message, send your response back to them using the appropriate send_{doc.channel.lower()}_message tool. "
				f"Be helpful, professional, and concise in your responses. "
				f"Reference: Sales Conversation {doc.name}"
			}
		] + history
		
		llm_response_obj = openai_responses_call(
			model_id="gpt-4.1", # Corrected model ID from user
			messages=enhanced_messages
		)
		print(f"--- BACKGROUND JOB: Step 2: LLM call successful for doc {doc.name} ---")

		# Extract the assistant's message for conversation history
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

		# The AI should have already sent the message using MCP tools
		# Check if any send_*_message tools were called in the response
		message_sent = False
		if hasattr(llm_response_obj, 'output') and llm_response_obj.output:
			for item in llm_response_obj.output:
				if hasattr(item, 'type') and item.type == 'mcp_call':
					tool_name = getattr(item, 'name', '')
					if tool_name in ['send_whatsapp_message', 'send_instagram_message']:
						message_sent = True
						print(f"--- BACKGROUND JOB: ✅ AI sent message using {tool_name} for doc {doc.name} ---")
						break
		
		if not message_sent:
			print(f"--- BACKGROUND JOB: ⚠️ AI did not send message, falling back to direct call for doc {doc.name} ---")
			# Fallback: direct call if AI didn't send the message
			if doc.channel == "WhatsApp":
				frappe.call(
					"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.send_whatsapp_message",
					to=doc.customer_identifier,
					message=bot_reply_text,
					reference_doctype="Sales Conversation",
					reference_name=doc.name
				)
				print(f"--- BACKGROUND JOB: Fallback WhatsApp message sent for doc {doc.name} ---")
			elif doc.channel == "Instagram":
				frappe.call(
					"frappe_whatsapp.frappe_whatsapp.doctype.instagram_message.instagram_message.send_instagram_message",
					to=doc.customer_identifier,
					message=bot_reply_text,
					reference_doctype="Sales Conversation",
					reference_name=doc.name
				)
				print(f"--- BACKGROUND JOB: Fallback Instagram message sent for doc {doc.name} ---")
		
		print(f"--- BACKGROUND JOB: FINISHED doc {doc.name} ---")

	except Exception as e:
		# This will print the exact error to the console
		print(f"--- BACKGROUND JOB: CRITICAL ERROR for doc {doc.name}: {e} ---")
		frappe.log_error(f"Sales Bot: Error during LLM call or processing. Error: {e}", doc.name)
		error_message = "I'm sorry, I'm having trouble connecting right now. Please try again in a moment."
		
		# Send error message using channel-specific methods
		try:
			if doc.channel == "WhatsApp":
				frappe.call(
					"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_message.whatsapp_message.send_whatsapp_message",
					to=doc.customer_identifier,
					message=error_message
				)
			elif doc.channel == "Instagram":
				frappe.call(
					"frappe_whatsapp.frappe_whatsapp.doctype.instagram_message.instagram_message.send_instagram_message",
					to=doc.customer_identifier,
					message=error_message
				)
			else:
				print(f"--- ERROR: Cannot send error message, unsupported channel {doc.channel} ---")
		except Exception as send_error:
			print(f"--- ERROR: Failed to send error message: {send_error} ---")
			frappe.log_error(f"Failed to send error message via {doc.channel}: {send_error}", "Sales Bot Error Send Failed")

@frappe.whitelist()
def ingest_message(channel: str, customer_identifier: str, user_message: str):
	try:
		print(f"=== INGESTING MESSAGE ===")
		print(f"Channel: {channel}, Customer: {customer_identifier}, Message: {user_message[:50]}...")
		
		doc_name = frappe.db.exists(
			"Sales Conversation", {"customer_identifier": customer_identifier, "channel": channel, "status": "Ongoing"}
		)

		if not doc_name:
			print(f"Creating new Sales Conversation for {channel} - {customer_identifier}")
			doc = frappe.new_doc("Sales Conversation")
			doc.channel = channel
			doc.customer_identifier = customer_identifier
			doc.insert(ignore_permissions=True)
			doc_name = doc.name
			print(f"Created Sales Conversation: {doc_name}")
		else:
			print(f"Found existing Sales Conversation: {doc_name}")
		
		# Correct enqueue path
		frappe.enqueue(
			"frappe_ai.frappe_ai.doctype.sales_conversation.sales_conversation.process_message",
			queue="short",
			docname=doc_name,
			user_message=user_message
		)
		
		print(f"✅ Message enqueued for processing: {doc_name}")
		return {"status": "success", "message": "Message enqueued for processing.", "conversation_id": doc_name}
	
	except Exception as e:
		print(f"❌ ERROR in ingest_message: {str(e)}")
		frappe.log_error("ingest_message: CRITICAL ERROR", str(e))
		raise 