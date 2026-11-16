# Copyright (c) 2026, Banking API and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, today

class FinacleUserAccessRequest(Document):
	def validate(self):
		self.validate_maker_checker()
		self.validate_dates()

	def validate_maker_checker(self):
		if self.status == "Draft":
			self.maker_id = frappe.session.user
			self.maker_datetime = now_datetime()
			self.maker_ip = getattr(frappe.local, "request_ip", None) or ""

	def validate_dates(self):
		if self.request_type == "Deputation":
			if self.from_date and self.to_date and self.to_date < self.from_date:
				frappe.throw("To Date cannot be before From Date")
			if self.current_sol_id and self.depute_sol_id and self.current_sol_id == self.depute_sol_id:
				frappe.throw("Depute SOL ID cannot be same as Current SOL ID")

	@frappe.whitelist()
	def submit_to_checker(self):
		if self.status != "Draft":
			frappe.throw("Only Draft requests can be sent to Checker")
		self.status = "Pending Checker Approval"
		self.maker_id = frappe.session.user
		self.maker_datetime = now_datetime()
		self.maker_ip = getattr(frappe.local, "request_ip", None) or ""
		self.save()

	@frappe.whitelist()
	def approve_request(self, remarks=None):
		if self.status != "Pending Checker Approval":
			frappe.throw("Only pending requests can be approved")
		if frappe.session.user == self.maker_id:
			frappe.throw("Maker and Checker cannot be the same user")

		self.checker_id = frappe.session.user
		self.checker_datetime = now_datetime()
		self.checker_remarks = remarks or self.checker_remarks
		self.status = "Active" if self.request_type == "Deputation" else "Approved"
		
		if self.request_type == "Deputation":
			self.execute_deputation_in_finacle()

		self.save()

	@frappe.whitelist()
	def reject_request(self, remarks):
		if not remarks:
			frappe.throw("Remarks are mandatory for rejection")
		if self.status != "Pending Checker Approval":
			frappe.throw("Only pending requests can be rejected")
		if frappe.session.user == self.maker_id:
			frappe.throw("Maker and Checker cannot be the same user")

		self.checker_id = frappe.session.user
		self.checker_datetime = now_datetime()
		self.checker_remarks = remarks
		self.status = "Rejected"
		self.save()

	@frappe.whitelist()
	def reverse_deputation(self, remarks=None):
		if self.request_type != "Deputation" or self.status != "Active":
			frappe.throw("Only active deputations can be reversed")
		self.is_reversed = 1
		self.reversal_date = now_datetime()
		self.status = "Reversed"
		if remarks:
			self.remarks = (self.remarks or "") + f"\nReversal Remark: {remarks}"
		
		self.execute_reversal_in_finacle()
		self.save()

	def execute_deputation_in_finacle(self):
		# Backend DB query hook: temporary SOL ID assign karna
		# frappe.db.sql(...) ya direct API sync
		pass

	def execute_reversal_in_finacle(self):
		# Backend DB query hook: user wapas current_sol_id par map hoga
		pass
