// Copyright (c) 2026, Banking API and contributors
// For license information, please see license.txt

frappe.ui.form.on('Finacle User Access Request', {
    refresh: function(frm) {
        set_action_buttons(frm);
    },
    employee: function(frm) {
        if (frm.doc.employee) {
            frappe.db.get_value('Employee', frm.doc.employee, ['branch', 'department'], (r) => {
                if (r && r.branch && !frm.doc.current_sol_id) {
                    frm.set_value('current_sol_id', r.branch);
                }
            });
        }
    }
});

function set_action_buttons(frm) {
    if (frm.is_new()) return;

    // Maker Submit Action
    if (frm.doc.status === 'Draft' && frappe.session.user === frm.doc.owner) {
        frm.add_custom_button(__('Send to Checker'), function() {
            frappe.confirm(__('Are you sure you want to submit this to Checker?'), () => {
                frm.call('submit_to_checker').then(() => frm.reload_doc());
            });
        }).addClass('btn-primary');
    }

    // Checker Actions
    if (frm.doc.status === 'Pending Checker Approval' && frappe.session.user !== frm.doc.maker_id) {
        frm.add_custom_button(__('Approve'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Approval Remarks') }
            ], function(values) {
                frm.call('approve_request', { remarks: values.remarks }).then(() => frm.reload_doc());
            }, __('Approve Request'), __('Approve'));
        }).addClass('btn-success');

        frm.add_custom_button(__('Reject'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Rejection Remarks'), reqd: 1 }
            ], function(values) {
                frm.call('reject_request', { remarks: values.remarks }).then(() => frm.reload_doc());
            }, __('Reject Request'), __('Reject'));
        }).addClass('btn-danger');
    }

    // Reverse Deputation Action
    if (frm.doc.request_type === 'Deputation' && frm.doc.status === 'Active' && !frm.doc.is_reversed) {
        frm.add_custom_button(__('Reverse Deputation'), function() {
            frappe.prompt([
                { fieldname: 'remarks', fieldtype: 'Small Text', label: __('Reason for Reversal'), reqd: 1 }
            ], function(values) {
                frm.call('reverse_deputation', { remarks: values.remarks }).then(() => frm.reload_doc());
            }, __('Reverse Deputation'), __('Confirm Reversal'));
        }).addClass('btn-warning');
    }
}
