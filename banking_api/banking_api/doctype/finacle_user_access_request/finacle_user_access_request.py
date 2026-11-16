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
			# Look up active Database Configuration dynamically
			db_config = frappe.db.get_value(
				"Database Configuration",
				{"database_name": ["in", ["Finacle", "postgres", "finfadm"]]},
				"name"
			) or frappe.db.get_value("Database Configuration", {}, "name")

			if not db_config:
				frappe.log_error(
					f"No Database Configuration found. Skipped {action} for {self.user_id}",
					f"Finacle {action} DB Config Missing"
				)
				return

			conn = get_db_connection(name=db_config, timeout=15)

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


def process_deputation_daily_scheduler():
	"""
	Daily scheduler job:
	1. 3-day advance alert for expiring deputations
	2. Auto-expire and auto-revert deputations whose to_date has passed
	3. Reminder for pending checker requests older than 3 days
	"""
	from frappe.utils import add_days, getdate

	current_date = getdate(today())
	reminder_date = add_days(current_date, 3)

	# 1. 3-day advance expiry reminder
	expiring_soon = frappe.get_all(
		"Finacle User Access Request",
		filters={
			"request_type": "Deputation",
			"status": "Active",
			"to_date": reminder_date,
			"is_reversed": 0
		},
		fields=["name", "user_id", "employee_name", "depute_sol_id", "current_sol_id", "to_date", "maker_id", "checker_id"]
	)

	for req in expiring_soon:
		subject = f"Deputation Ending Soon (3 Days): {req.employee_name or req.user_id}"
		message = f"Deputation for user {req.user_id} at branch {req.depute_sol_id} will expire on {req.to_date}. Base SOL: {req.current_sol_id}."
		recipients = list(filter(None, [req.maker_id, req.checker_id]))
		if recipients:
			for user in recipients:
				frappe.publish_realtime("msgprint", message, user=user)

	# 2. Auto-expiry and auto-revert
	expired_requests = frappe.get_all(
		"Finacle User Access Request",
		filters={
			"request_type": "Deputation",
			"status": "Active",
			"to_date": ["<", current_date],
			"is_reversed": 0
		},
		fields=["name"]
	)

	for r in expired_requests:
		try:
			doc = frappe.get_doc("Finacle User Access Request", r.name)
			doc.status = "Expired"
			doc.is_reversed = 1
			doc.reversal_date = now_datetime()
			doc.remarks = (doc.remarks or "") + "\nAuto-expired and reverted by daily scheduler."
			doc.execute_reversal_in_finacle()
			doc.save(ignore_permissions=True)
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"Auto-revert failed for deputation {r.name}")

	# 3. Reminder for pending approvals >= 3 days old
	pending_cutoff = add_days(current_date, -3)
	pending_requests = frappe.get_all(
		"Finacle User Access Request",
		filters={
			"status": "Pending Checker Approval",
			"creation": ["<=", pending_cutoff]
		},
		fields=["name", "employee_name", "user_id", "checker_id", "creation"]
	)

	for p in pending_requests:
		if p.checker_id:
			frappe.publish_realtime(
				"msgprint",
				f"Reminder: Deputation request {p.name} for {p.employee_name or p.user_id} is pending your approval for 3+ days.",
				user=p.checker_id
			)

