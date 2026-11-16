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
		"""
		Updates Finacle user's SOL ID to depute_sol_id upon checker approval.
		"""
		self._update_finacle_sol(target_sol=self.depute_sol_id, action="Deputation")

	def execute_reversal_in_finacle(self):
		"""
		Restores Finacle user's SOL ID to current_sol_id upon reversal or expiry.
		"""
		self._update_finacle_sol(target_sol=self.current_sol_id, action="Reversal")

	def _update_finacle_sol(self, target_sol, action="Update"):
		if not self.user_id or not target_sol:
			return

		from banking_api.banking_api.doctype.database_configuration.database_configuration import (
			get_db_connection,
		)

		conn = None
		try:
			if frappe.db.exists("Database Configuration", {"database": "Finacle Production"}):
				conn = get_db_connection(database="Finacle Production", timeout=15)
			elif frappe.db.exists("Database Configuration", {"name": "Finacle Production"}):
				conn = get_db_connection(name="Finacle Production", timeout=15)
			elif frappe.db.exists("Database Configuration", {"database": "Finacle Production DR"}):
				conn = get_db_connection(database="Finacle Production DR", timeout=15)
			else:
				frappe.log_error(
					f"Database Configuration for Finacle not found. Skipped {action} for {self.user_id}",
					f"Finacle {action} DB Config Missing"
				)
				return

			cur = conn.cursor()
			# Update SOL in employee get table
			query_get = 'UPDATE tbaadm."get" SET sol_id = %s WHERE emp_id = %s;'
			cur.execute(query_get, (target_sol, self.user_id))

			# Update SOL in user profile table
			query_prof = 'UPDATE finfadm.user_profile_tbl SET sol_id = %s WHERE user_id = %s;'
			cur.execute(query_prof, (target_sol, self.user_id))

			conn.commit()
			conn.close()
		except Exception as e:
			if conn:
				try:
					conn.rollback()
					conn.close()
				except Exception:
					pass
			frappe.log_error(frappe.get_traceback(), f"Finacle {action} failed for {self.user_id}")
			frappe.throw(f"Failed to execute {action} in Finacle: {str(e)}")
