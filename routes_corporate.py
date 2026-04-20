"""
Builds #235-237 — Corporate Workspaces (Travel+ Business)

"Slack for Travel" — companies buy per-seat travel management for employees.
Admin controls, travel policies, approval workflows, book-on-behalf, export.

Build #235 — Workspace Model + Admin + Roles + Invites:
  POST   /api/workspaces                          — create workspace
  GET    /api/workspaces                          — list my workspaces
  GET    /api/workspaces/<slug>                   — get workspace detail
  PUT    /api/workspaces/<slug>                   — update workspace settings
  POST   /api/workspaces/<slug>/members           — invite member (by email)
  GET    /api/workspaces/<slug>/members           — list members
  PUT    /api/workspaces/<slug>/members/<mid>     — update member role/type/dept
  DELETE /api/workspaces/<slug>/members/<mid>     — remove member
  POST   /api/workspaces/join/<code>              — join via invite code

Build #236 — Travel Policies + Approval Workflows + Expense Tags:
  POST   /api/workspaces/<slug>/policies          — create policy
  GET    /api/workspaces/<slug>/policies          — list policies
  PUT    /api/workspaces/<slug>/policies/<pid>    — update policy
  DELETE /api/workspaces/<slug>/policies/<pid>    — delete policy
  POST   /api/workspaces/<slug>/approvals         — request approval
  GET    /api/workspaces/<slug>/approvals         — list approvals (filtered)
  PUT    /api/workspaces/<slug>/approvals/<aid>   — approve or deny

Build #237 — Corporate Dashboard + Book-on-Behalf + Export:
  GET    /api/workspaces/<slug>/dashboard         — spending summary + charts
  POST   /api/workspaces/<slug>/book-on-behalf    — book for another member
  GET    /api/workspaces/<slug>/bookings          — all workspace bookings
  GET    /api/workspaces/<slug>/export             — CSV export of bookings

Registration: register_corporate_routes(app, csrf, limiter)
"""

import csv
import io
import json
import logging
import secrets
from datetime import datetime, timezone

from flask import request, jsonify, Response
from flask_login import current_user, login_required

from models import (
    db, User, Booking, FeatureFlag, TripPlan, TripMember, ItineraryItem,
    Workspace, WorkspaceMember, TravelPolicy, BookingApproval,
)

logger = logging.getLogger(__name__)


def _utcnow():
    return datetime.now(timezone.utc)


def _check_flag(flag_key):
    """Return error response if flag is disabled, else None."""
    if not FeatureFlag.is_flag_enabled(flag_key):
        return jsonify({
            'status': 'error',
            'error': f'Feature "{flag_key}" is not enabled',
        }), 403
    return None


def _get_workspace(slug):
    """Fetch workspace by slug, return (workspace, error_response)."""
    ws = Workspace.query.filter_by(slug=slug, is_active=True).first()
    if not ws:
        return None, (jsonify({'status': 'error', 'error': 'Workspace not found'}), 404)
    return ws, None


def _get_membership(ws):
    """Get current user's membership in workspace, return (member, error_response)."""
    member = WorkspaceMember.query.filter_by(
        workspace_id=ws.id, user_id=current_user.id, is_active=True
    ).first()
    if not member:
        return None, (jsonify({'status': 'error', 'error': 'Not a workspace member'}), 403)
    return member, None


def _require_admin(ws):
    """Require admin role in workspace. Returns (member, error_response)."""
    member, err = _get_membership(ws)
    if err:
        return None, err
    if member.role != 'admin':
        return None, (jsonify({'status': 'error', 'error': 'Admin role required'}), 403)
    return member, None


def _require_admin_or_manager(ws):
    """Require admin or travel_manager role."""
    member, err = _get_membership(ws)
    if err:
        return None, err
    if not member.is_admin_or_manager():
        return None, (jsonify({'status': 'error', 'error': 'Admin or travel manager role required'}), 403)
    return member, None


def _generate_invite_code():
    """Generate a unique workspace invite code."""
    for _ in range(10):
        code = f"WS-{secrets.token_hex(4).upper()}"
        if not Workspace.query.filter_by(invite_code=code).first():
            return code
    return f"WS-{secrets.token_hex(6).upper()}"


def _generate_slug(name):
    """Generate a URL-safe slug from workspace name."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40]
    if not slug:
        slug = 'workspace'
    base = slug
    counter = 1
    while Workspace.query.filter_by(slug=slug).first():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def register_corporate_routes(app, csrf, limiter):
    """Register corporate workspace routes (Builds #235-237)."""

    # ══════════════════════════════════════════════════
    # BUILD #235 — WORKSPACE MODEL + ADMIN + ROLES
    # ══════════════════════════════════════════════════

    @app.route('/api/workspaces', methods=['POST'])
    @login_required
    def create_workspace():
        """Create a new corporate workspace. Creator becomes admin."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'error': 'Workspace name required'}), 400

        tier = data.get('tier', 'starter')
        if tier not in Workspace.TIERS:
            return jsonify({'status': 'error', 'error': f'Invalid tier. Must be one of: {", ".join(Workspace.TIERS)}'}), 400

        max_seats = {'starter': 25, 'pro': 100, 'enterprise': 9999}.get(tier, 25)

        ws = Workspace(
            name=name,
            slug=_generate_slug(name),
            owner_user_id=current_user.id,
            company_domain=data.get('company_domain', '').strip() or None,
            company_logo_url=data.get('company_logo_url', '').strip() or None,
            industry=data.get('industry', '').strip() or None,
            tier=tier,
            max_seats=max_seats,
            invite_code=_generate_invite_code(),
            domain_auto_join=bool(data.get('domain_auto_join', False)),
        )
        db.session.add(ws)
        db.session.flush()

        # Creator is auto-enrolled as admin employee
        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=current_user.id,
            role='admin',
            member_type='employee',
            invited_by_user_id=current_user.id,
        )
        db.session.add(member)
        db.session.commit()

        logger.info("Workspace created: %s (slug=%s) by user %s", name, ws.slug, current_user.id)
        return jsonify({
            'status': 'ok',
            'workspace': ws.to_dict(include_stats=True),
        })

    @app.route('/api/workspaces', methods=['GET'])
    @login_required
    def list_workspaces():
        """List workspaces the current user belongs to."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        memberships = WorkspaceMember.query.filter_by(
            user_id=current_user.id, is_active=True
        ).all()

        result = []
        for m in memberships:
            ws = Workspace.query.get(m.workspace_id)
            if ws and ws.is_active:
                d = ws.to_dict(include_stats=True)
                d['my_role'] = m.role
                d['my_member_type'] = m.member_type
                result.append(d)

        return jsonify({'status': 'ok', 'workspaces': result})

    @app.route('/api/workspaces/<slug>', methods=['GET'])
    @login_required
    def get_workspace(slug):
        """Get workspace details (members only)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err

        member, err = _get_membership(ws)
        if err:
            return err

        d = ws.to_dict(include_stats=True)
        d['my_role'] = member.role
        d['my_member_type'] = member.member_type
        d['my_department'] = member.department
        return jsonify({'status': 'ok', 'workspace': d})

    @app.route('/api/workspaces/<slug>', methods=['PUT'])
    @login_required
    def update_workspace(slug):
        """Update workspace settings (admin only)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}

        if 'name' in data and data['name'].strip():
            ws.name = data['name'].strip()
        if 'company_domain' in data:
            ws.company_domain = data['company_domain'].strip() or None
        if 'company_logo_url' in data:
            ws.company_logo_url = data['company_logo_url'].strip() or None
        if 'industry' in data:
            ws.industry = data['industry'].strip() or None
        if 'domain_auto_join' in data:
            ws.domain_auto_join = bool(data['domain_auto_join'])
        if 'tier' in data and data['tier'] in Workspace.TIERS:
            ws.tier = data['tier']
            ws.max_seats = {'starter': 25, 'pro': 100, 'enterprise': 9999}.get(ws.tier, 25)

        db.session.commit()
        return jsonify({'status': 'ok', 'workspace': ws.to_dict(include_stats=True)})

    # ── Member Management ──

    @app.route('/api/workspaces/<slug>/members', methods=['POST'])
    @login_required
    def invite_workspace_member(slug):
        """Invite a member to the workspace (admin or travel_manager)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        email = (data.get('email') or '').strip().lower()
        if not email:
            return jsonify({'status': 'error', 'error': 'Email required'}), 400

        # Check seat limit
        if ws.seat_count() >= ws.max_seats:
            return jsonify({'status': 'error', 'error': f'Seat limit reached ({ws.max_seats})'}), 400

        # Find or validate user
        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({'status': 'error', 'error': 'User not found. They must create a MYSTES account first.'}), 404

        # Check not already a member
        existing = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, user_id=user.id
        ).first()
        if existing:
            if existing.is_active:
                return jsonify({'status': 'error', 'error': 'User is already a member'}), 409
            # Re-activate
            existing.is_active = True
            existing.role = data.get('role', 'member')
            existing.member_type = data.get('member_type', 'employee')
            existing.department = data.get('department', '').strip() or None
            db.session.commit()
            return jsonify({'status': 'ok', 'member': existing.to_dict()})

        role = data.get('role', 'member')
        if role not in WorkspaceMember.ROLES:
            role = 'member'
        member_type = data.get('member_type', 'employee')
        if member_type not in WorkspaceMember.MEMBER_TYPES:
            member_type = 'employee'

        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=user.id,
            role=role,
            member_type=member_type,
            department=data.get('department', '').strip() or None,
            invited_by_user_id=current_user.id,
        )
        db.session.add(member)
        db.session.commit()

        logger.info("Workspace member added: user=%s ws=%s role=%s", user.id, ws.slug, role)
        return jsonify({'status': 'ok', 'member': member.to_dict()})

    @app.route('/api/workspaces/<slug>/members', methods=['GET'])
    @login_required
    def list_workspace_members(slug):
        """List all workspace members (any member can view)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _get_membership(ws)
        if err:
            return err

        members = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, is_active=True
        ).order_by(WorkspaceMember.role, WorkspaceMember.joined_at).all()

        return jsonify({
            'status': 'ok',
            'members': [m.to_dict() for m in members],
            'total': len(members),
        })

    @app.route('/api/workspaces/<slug>/members/<int:member_id>', methods=['PUT'])
    @login_required
    def update_workspace_member(slug, member_id):
        """Update member role, type, or department (admin only)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        member = WorkspaceMember.query.filter_by(
            id=member_id, workspace_id=ws.id
        ).first()
        if not member:
            return jsonify({'status': 'error', 'error': 'Member not found'}), 404

        # Cannot demote the workspace owner
        if member.user_id == ws.owner_user_id and member.role == 'admin':
            data = request.get_json(silent=True) or {}
            if data.get('role') and data['role'] != 'admin':
                return jsonify({'status': 'error', 'error': 'Cannot demote workspace owner'}), 400

        data = request.get_json(silent=True) or {}
        if 'role' in data and data['role'] in WorkspaceMember.ROLES:
            member.role = data['role']
        if 'member_type' in data and data['member_type'] in WorkspaceMember.MEMBER_TYPES:
            member.member_type = data['member_type']
        if 'department' in data:
            member.department = data['department'].strip() or None

        db.session.commit()
        return jsonify({'status': 'ok', 'member': member.to_dict()})

    @app.route('/api/workspaces/<slug>/members/<int:member_id>', methods=['DELETE'])
    @login_required
    def remove_workspace_member(slug, member_id):
        """Remove member from workspace (admin only, cannot remove owner)."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        member = WorkspaceMember.query.filter_by(
            id=member_id, workspace_id=ws.id
        ).first()
        if not member:
            return jsonify({'status': 'error', 'error': 'Member not found'}), 404

        if member.user_id == ws.owner_user_id:
            return jsonify({'status': 'error', 'error': 'Cannot remove workspace owner'}), 400

        member.is_active = False
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Member removed'})

    @app.route('/api/workspaces/join/<code>', methods=['POST'])
    @login_required
    def join_workspace_by_code(code):
        """Join a workspace via invite code."""
        blocked = _check_flag('corporate_workspaces')
        if blocked:
            return blocked

        ws = Workspace.query.filter_by(invite_code=code, is_active=True).first()
        if not ws:
            return jsonify({'status': 'error', 'error': 'Invalid invite code'}), 404

        # Check seat limit
        if ws.seat_count() >= ws.max_seats:
            return jsonify({'status': 'error', 'error': 'Workspace is full'}), 400

        # Already member?
        existing = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, user_id=current_user.id
        ).first()
        if existing:
            if existing.is_active:
                return jsonify({'status': 'error', 'error': 'Already a member'}), 409
            existing.is_active = True
            db.session.commit()
            return jsonify({'status': 'ok', 'workspace': ws.to_dict(), 'member': existing.to_dict()})

        member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=current_user.id,
            role='member',
            member_type='employee',
        )
        db.session.add(member)
        db.session.commit()

        return jsonify({'status': 'ok', 'workspace': ws.to_dict(), 'member': member.to_dict()})

    # ══════════════════════════════════════════════════
    # BUILD #236 — TRAVEL POLICIES + APPROVALS
    # ══════════════════════════════════════════════════

    @app.route('/api/workspaces/<slug>/policies', methods=['POST'])
    @login_required
    def create_travel_policy(slug):
        """Create a travel policy (admin only)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'status': 'error', 'error': 'Policy name required'}), 400

        policy = TravelPolicy(
            workspace_id=ws.id,
            name=name,
            description=data.get('description', '').strip() or None,
            max_flight_usd=data.get('max_flight_usd'),
            max_hotel_per_night_usd=data.get('max_hotel_per_night_usd'),
            max_total_trip_usd=data.get('max_total_trip_usd'),
            preferred_airlines=data.get('preferred_airlines', '').strip() or None,
            preferred_cabin=data.get('preferred_cabin', '').strip() or None,
            blackout_dates_json=json.dumps(data['blackout_dates']) if data.get('blackout_dates') else None,
            approval_threshold_usd=data.get('approval_threshold_usd'),
            advance_booking_days=data.get('advance_booking_days'),
            applies_to_department=data.get('applies_to_department', '').strip() or None,
            applies_to_member_type=data.get('applies_to_member_type', '').strip() or None,
            created_by_user_id=current_user.id,
        )
        db.session.add(policy)
        db.session.commit()

        return jsonify({'status': 'ok', 'policy': policy.to_dict()})

    @app.route('/api/workspaces/<slug>/policies', methods=['GET'])
    @login_required
    def list_travel_policies(slug):
        """List all active travel policies in workspace (any member)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _get_membership(ws)
        if err:
            return err

        policies = TravelPolicy.query.filter_by(
            workspace_id=ws.id, is_active=True
        ).order_by(TravelPolicy.created_at).all()

        return jsonify({
            'status': 'ok',
            'policies': [p.to_dict() for p in policies],
        })

    @app.route('/api/workspaces/<slug>/policies/<int:policy_id>', methods=['PUT'])
    @login_required
    def update_travel_policy(slug, policy_id):
        """Update a travel policy (admin only)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        policy = TravelPolicy.query.filter_by(id=policy_id, workspace_id=ws.id).first()
        if not policy:
            return jsonify({'status': 'error', 'error': 'Policy not found'}), 404

        data = request.get_json(silent=True) or {}
        for field in ['name', 'description', 'preferred_airlines', 'preferred_cabin',
                       'applies_to_department', 'applies_to_member_type']:
            if field in data:
                setattr(policy, field, (data[field] or '').strip() or None)
        for field in ['max_flight_usd', 'max_hotel_per_night_usd', 'max_total_trip_usd',
                       'approval_threshold_usd', 'advance_booking_days']:
            if field in data:
                setattr(policy, field, data[field])
        if 'blackout_dates' in data:
            policy.blackout_dates_json = json.dumps(data['blackout_dates']) if data['blackout_dates'] else None

        db.session.commit()
        return jsonify({'status': 'ok', 'policy': policy.to_dict()})

    @app.route('/api/workspaces/<slug>/policies/<int:policy_id>', methods=['DELETE'])
    @login_required
    def delete_travel_policy(slug, policy_id):
        """Delete a travel policy (admin only, soft delete)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin(ws)
        if err:
            return err

        policy = TravelPolicy.query.filter_by(id=policy_id, workspace_id=ws.id).first()
        if not policy:
            return jsonify({'status': 'error', 'error': 'Policy not found'}), 404

        policy.is_active = False
        db.session.commit()
        return jsonify({'status': 'ok', 'message': 'Policy deleted'})

    # ── Approval Workflow ──

    @app.route('/api/workspaces/<slug>/approvals', methods=['POST'])
    @login_required
    def request_booking_approval(slug):
        """Request approval for a booking that exceeds policy thresholds."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        booking_type = (data.get('booking_type') or '').strip()
        estimated_cost = data.get('estimated_cost_usd')

        if not booking_type:
            return jsonify({'status': 'error', 'error': 'booking_type required'}), 400
        if estimated_cost is None or estimated_cost < 0:
            return jsonify({'status': 'error', 'error': 'estimated_cost_usd required'}), 400

        # Find applicable policy to record why approval is needed
        policy_id = None
        policy_reason = None
        policies = TravelPolicy.query.filter_by(workspace_id=ws.id, is_active=True).all()
        for p in policies:
            # Check department scope
            if p.applies_to_department and p.applies_to_department != member.department:
                continue
            if p.applies_to_member_type and p.applies_to_member_type != member.member_type:
                continue
            # Check threshold
            if p.approval_threshold_usd and estimated_cost > p.approval_threshold_usd:
                policy_id = p.id
                policy_reason = f"Exceeds approval threshold (${p.approval_threshold_usd:.0f}) per '{p.name}'"
                break
            if booking_type == 'flight' and p.max_flight_usd and estimated_cost > p.max_flight_usd:
                policy_id = p.id
                policy_reason = f"Exceeds max flight cost (${p.max_flight_usd:.0f}) per '{p.name}'"
                break
            if booking_type == 'hotel' and p.max_hotel_per_night_usd:
                per_night = data.get('per_night_usd', estimated_cost)
                if per_night > p.max_hotel_per_night_usd:
                    policy_id = p.id
                    policy_reason = f"Exceeds max hotel per night (${p.max_hotel_per_night_usd:.0f}) per '{p.name}'"
                    break

        approval = BookingApproval(
            workspace_id=ws.id,
            requester_user_id=current_user.id,
            booking_type=booking_type,
            description=data.get('description', '').strip() or None,
            estimated_cost_usd=estimated_cost,
            trip_id=data.get('trip_id'),
            itinerary_item_id=data.get('itinerary_item_id'),
            policy_id=policy_id,
            policy_reason=policy_reason,
            expense_tag=data.get('expense_tag', '').strip() or None,
            department=member.department,
            is_business=data.get('is_business', True),
        )
        db.session.add(approval)
        db.session.commit()

        return jsonify({'status': 'ok', 'approval': approval.to_dict()})

    @app.route('/api/workspaces/<slug>/approvals', methods=['GET'])
    @login_required
    def list_booking_approvals(slug):
        """List booking approvals (admin/manager sees all, members see own)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        query = BookingApproval.query.filter_by(workspace_id=ws.id)

        # Members only see their own
        if not member.is_admin_or_manager():
            query = query.filter_by(requester_user_id=current_user.id)

        # Optional status filter
        status_filter = request.args.get('status')
        if status_filter and status_filter in BookingApproval.STATUSES:
            query = query.filter_by(status=status_filter)

        approvals = query.order_by(BookingApproval.created_at.desc()).limit(100).all()
        return jsonify({
            'status': 'ok',
            'approvals': [a.to_dict() for a in approvals],
        })

    @app.route('/api/workspaces/<slug>/approvals/<int:approval_id>', methods=['PUT'])
    @login_required
    def decide_booking_approval(slug, approval_id):
        """Approve or deny a booking request (admin or travel_manager)."""
        blocked = _check_flag('travel_policies')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        approval = BookingApproval.query.filter_by(
            id=approval_id, workspace_id=ws.id
        ).first()
        if not approval:
            return jsonify({'status': 'error', 'error': 'Approval not found'}), 404

        if approval.status != 'pending':
            return jsonify({'status': 'error', 'error': f'Already {approval.status}'}), 400

        data = request.get_json(silent=True) or {}
        decision = (data.get('decision') or '').strip()
        if decision not in ('approved', 'denied'):
            return jsonify({'status': 'error', 'error': 'Decision must be "approved" or "denied"'}), 400

        approval.status = decision
        approval.approver_user_id = current_user.id
        approval.approver_note = data.get('note', '').strip() or None
        approval.decided_at = _utcnow()
        db.session.commit()

        logger.info("Booking approval %s: id=%d ws=%s by user=%s",
                     decision, approval.id, slug, current_user.id)
        return jsonify({'status': 'ok', 'approval': approval.to_dict()})

    # ══════════════════════════════════════════════════
    # BUILD #237 — DASHBOARD + BOOK-ON-BEHALF + EXPORT
    # ══════════════════════════════════════════════════

    @app.route('/api/workspaces/<slug>/dashboard', methods=['GET'])
    @login_required
    def workspace_dashboard(slug):
        """Corporate dashboard — spending summary, member stats, approval queue."""
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        # Only admin/manager sees full dashboard
        is_elevated = member.is_admin_or_manager()

        # Member count by role
        members_q = WorkspaceMember.query.filter_by(workspace_id=ws.id, is_active=True)
        total_members = members_q.count()
        admins = members_q.filter_by(role='admin').count()
        managers = members_q.filter_by(role='travel_manager').count()

        # Booking stats — bookings from workspace members
        member_user_ids = [m.user_id for m in members_q.all()]

        total_bookings = 0
        total_spend = 0.0
        bookings_by_type = {}
        bookings_by_dept = {}

        if member_user_ids:
            bookings = Booking.query.filter(
                Booking.user_id.in_(member_user_ids),
                Booking.status.in_(['booked', 'completed']),
            ).all()
            total_bookings = len(bookings)
            for b in bookings:
                cost = b.vendor_payment_amount or 0
                total_spend += cost
                # Categorize (simplified — real impl would use expense tags)
                btype = 'flight'  # Default
                bookings_by_type[btype] = bookings_by_type.get(btype, 0) + 1

                # By department
                bm = WorkspaceMember.query.filter_by(
                    workspace_id=ws.id, user_id=b.user_id
                ).first()
                dept = bm.department if bm else 'Unassigned'
                bookings_by_dept[dept] = bookings_by_dept.get(dept, 0) + cost

        # Pending approvals count
        pending_approvals = BookingApproval.query.filter_by(
            workspace_id=ws.id, status='pending'
        ).count() if is_elevated else 0

        dashboard = {
            'workspace': ws.to_dict(include_stats=True),
            'members': {
                'total': total_members,
                'admins': admins,
                'travel_managers': managers,
                'regular_members': total_members - admins - managers,
            },
            'bookings': {
                'total': total_bookings,
                'total_spend_usd': round(total_spend, 2),
                'by_type': bookings_by_type,
                'by_department': {k: round(v, 2) for k, v in bookings_by_dept.items()},
            },
            'pending_approvals': pending_approvals,
            'tier_info': {
                'tier': ws.tier,
                'fee_percent': ws.fee_percent(),
                'per_seat_price': ws.per_seat_price(),
                'monthly_seat_cost': round(ws.per_seat_price() * total_members, 2),
                'base_cost': 9.99,
                'total_monthly': round(9.99 + ws.per_seat_price() * total_members, 2),
            },
        }

        return jsonify({'status': 'ok', 'dashboard': dashboard})

    @app.route('/api/workspaces/<slug>/book-on-behalf', methods=['POST'])
    @login_required
    def book_on_behalf(slug):
        """Admin/manager books a trip on behalf of another member.

        Creates a trip plan with the target member as owner, and the
        current user as the admin that initiated it.
        """
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        data = request.get_json(silent=True) or {}
        target_user_id = data.get('for_user_id')
        trip_name = (data.get('trip_name') or '').strip()

        if not target_user_id:
            return jsonify({'status': 'error', 'error': 'for_user_id required'}), 400
        if not trip_name:
            return jsonify({'status': 'error', 'error': 'trip_name required'}), 400

        # Verify target is a workspace member
        target_member = WorkspaceMember.query.filter_by(
            workspace_id=ws.id, user_id=target_user_id, is_active=True
        ).first()
        if not target_member:
            return jsonify({'status': 'error', 'error': 'Target user is not a workspace member'}), 404

        # Create trip owned by target, managed by current user
        trip = TripPlan(
            creator_id=target_user_id,
            name=trip_name,
            status='draft',
        )
        db.session.add(trip)
        db.session.flush()

        # Target is owner
        owner_member = TripMember(
            trip_plan_id=trip.id,
            user_id=target_user_id,
            role='owner',
            invitation_status='accepted',
            joined_at=_utcnow(),
        )
        db.session.add(owner_member)

        # Current user (admin/manager) is editor
        if current_user.id != target_user_id:
            admin_member = TripMember(
                trip_plan_id=trip.id,
                user_id=current_user.id,
                role='editor',
                invitation_status='accepted',
                joined_at=_utcnow(),
            )
            db.session.add(admin_member)

        db.session.commit()

        logger.info("Book-on-behalf: trip=%d for user=%d by admin=%d ws=%s",
                     trip.id, target_user_id, current_user.id, slug)
        return jsonify({
            'status': 'ok',
            'trip_id': trip.id,
            'trip_name': trip.name,
            'for_user_id': target_user_id,
            'for_user_name': target_member.user.name if target_member.user else None,
        })

    @app.route('/api/workspaces/<slug>/bookings', methods=['GET'])
    @login_required
    def workspace_bookings(slug):
        """List all bookings by workspace members (admin/manager: all, member: own)."""
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        member, err = _get_membership(ws)
        if err:
            return err

        if member.is_admin_or_manager():
            member_ids = [m.user_id for m in WorkspaceMember.query.filter_by(
                workspace_id=ws.id, is_active=True
            ).all()]
        else:
            member_ids = [current_user.id]

        bookings = Booking.query.filter(
            Booking.user_id.in_(member_ids)
        ).order_by(Booking.created_at.desc()).limit(200).all()

        result = []
        for b in bookings:
            wm = WorkspaceMember.query.filter_by(
                workspace_id=ws.id, user_id=b.user_id
            ).first()
            result.append({
                'booking_id': b.id,
                'user_id': b.user_id,
                'user_name': b.user.name if b.user else None,
                'department': wm.department if wm else None,
                'status': b.status,
                'confirmation_code': b.confirmation_code,
                'vendor_payment_amount': b.vendor_payment_amount,
                'vendor_payment_currency': b.vendor_payment_currency,
                'created_at': b.created_at.isoformat() if b.created_at else None,
            })

        return jsonify({'status': 'ok', 'bookings': result, 'total': len(result)})

    @app.route('/api/workspaces/<slug>/export', methods=['GET'])
    @login_required
    def export_workspace_bookings(slug):
        """Export workspace bookings as CSV (admin/manager only)."""
        blocked = _check_flag('corporate_dashboard')
        if blocked:
            return blocked

        ws, err = _get_workspace(slug)
        if err:
            return err
        _, err = _require_admin_or_manager(ws)
        if err:
            return err

        member_ids = [m.user_id for m in WorkspaceMember.query.filter_by(
            workspace_id=ws.id, is_active=True
        ).all()]

        bookings = Booking.query.filter(
            Booking.user_id.in_(member_ids)
        ).order_by(Booking.created_at.desc()).all()

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Booking ID', 'Employee', 'Email', 'Department', 'Status',
            'Confirmation Code', 'Amount', 'Currency', 'Date',
        ])

        for b in bookings:
            wm = WorkspaceMember.query.filter_by(
                workspace_id=ws.id, user_id=b.user_id
            ).first()
            writer.writerow([
                b.id,
                b.user.name if b.user else '',
                b.user.email if b.user else '',
                wm.department if wm else '',
                b.status,
                b.confirmation_code or '',
                b.vendor_payment_amount or 0,
                b.vendor_payment_currency or 'USD',
                b.created_at.isoformat() if b.created_at else '',
            ])

        csv_data = output.getvalue()
        output.close()

        return Response(
            csv_data,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename={ws.slug}-bookings.csv',
            },
        )
