# Copyright (c) 2025, arvis and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import requests
from typing import TYPE_CHECKING
from frappe.types import DF

	

class AISetting(Document):
	enable_openrouter: DF.Check
	site_api_key: DF.Password | None
	openrouter_user_id: DF.Data | None
	key_provisioned: DF.Check
	key_hash: DF.Data | None

	def before_save(self):
		if self.enable_openrouter and not self.key_provisioned:
			self._provision_and_set_key()
		
		if not self.enable_openrouter and self.key_provisioned:
			self._delete_key()	
			# self.key_provisioned = 0
			# self.key_hash = None
			# self.site_api_key = None
			# self.openrouter_user_id = None
			

	def on_update(self):
		if getattr(self, "_new_key_provisioned", False):
			frappe.msgprint(frappe._("Successfully provisioned and saved OpenRouter API Key!"), indicator="green", alert=True)
	

	def _delete_key(self):
		print("Deleting key")
		key_hash = self.key_hash
		master_key = frappe.conf.get("openrouter_provisioning_key")
		if not master_key:
			frappe.throw("OpenRouter Provisioning Key is not set in common_sites_config.json.")

		try:
			response = requests.delete(
				f"https://openrouter.ai/api/v1/keys/{key_hash}",
				headers={
					"Authorization": f"Bearer {master_key}",
					"Content-Type": "application/json"
				}
			)
			response.raise_for_status()
			frappe.msgprint(frappe._("Successfully deleted OpenRouter API Key!"), indicator="green", alert=True)
			
			self.key_provisioned = 0
			self.key_hash = None
			self.site_api_key = None
			self.openrouter_user_id = None

		except requests.exceptions.RequestException as e:
			frappe.log_error(f"OpenRouter API Error: {e}")
			frappe.throw(f"Failed to communicate with OpenRouter API. Details: {e}")
		except Exception as e:
			frappe.log_error(f"An unexpected error occurred during key deletion: {e}")
			frappe.throw(f"An unexpected error occurred. Please check logs.")
		
	
	
	def _provision_and_set_key(self):
		print("Provisioning and setting key")
		master_key = frappe.conf.get("openrouter_provisioning_key")
		if not master_key:
			frappe.throw("OpenRouter Provisioning Key is not set in common_sites_config.json.")

		key_name = frappe.local.site

		try:
			response = requests.post(
				"https://openrouter.ai/api/v1/keys",
				headers={"Authorization": f"Bearer {master_key}"},
				json={"name": key_name}
			)
			response.raise_for_status()  # This will raise an error for 4xx/5xx responses
			key_data = response.json()

		except requests.exceptions.RequestException as e:
			frappe.log_error(f"OpenRouter API Error: {e}")
			frappe.throw(f"Failed to communicate with OpenRouter API. Details: {e}")
		except Exception as e:
			frappe.log_error(f"An unexpected error occurred during key provisioning: {e}")
			frappe.throw(f"An unexpected error occurred. Please check logs.")

		try:
			print(f"---OpenRouter Raw Response: {key_data}---")
			data = key_data.get("data")
			key=key_data.get("key")
			
			
			key_hash = data.get("hash")
			openrouter_user_id = data.get("name")
		except (IndexError, TypeError, KeyError, AttributeError) as e:
			frappe.log_error(f"Could not parse OpenRouter response. Error: {e}. Response was: {key_data}")
			frappe.throw("Could not parse the response from OpenRouter. Please confirm the format in the logs.")
			
		if not key or not key_hash:
			frappe.log_error(f"OpenRouter did not return the expected key/id. Response: {key_data}")
			frappe.throw("Could not parse the response from OpenRouter. The response format might have changed.")

		self.site_api_key = key
		self.openrouter_user_id = openrouter_user_id
		self.key_provisioned = 1
		self.key_hash = key_hash

