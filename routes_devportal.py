"""
APAi Admin Portal Routes — Build #194

Multi-seat team management for APAi subscribers. ANASTASiA dev terminal.
Repurposed from standalone Dev Portal (Build #184). Standalone product SCRAPPED.
ANASTASiA is APAi-exclusive — no open access outside the ecosystem.

Routes:
    GET  /apai/admin                    — Dashboard (team + usage)
    GET  /apai/admin/login              — Login
    POST /apai/admin/login              — Authenticate
    GET  /apai/admin/logout             — Logout
    GET  /apai/admin/terminal           — ANASTASiA dev terminal
    POST /api/apai/admin/chat           — Chat endpoint
    GET  /api/apai/admin/conversations  — List conversations
    POST /api/apai/admin/conversations  — Create conversation
    GET  /api/apai/admin/conversations/<id> — Get conversation
    DELETE /api/apai/admin/conversations/<id> — Delete conversation
    GET  /api/apai/admin/usage          — Usage stats
    GET  /api/apai/admin/account        — Account info
    POST /api/apai/admin/team           — Add team member
    DELETE /api/apai/admin/team/<id>    — Remove team member
    PUT  /api/apai/admin/team/<id>      — Update team member (query limit)
    GET  /apai/admin/api-keys           — Key management
    POST /apai/admin/api-keys           — Generate key
    DELETE /api/apai/admin/api-keys/<id> — Revoke key

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import os
import secrets
from datetime import datetime, timezone
from functools import wraps

import bcrypt
from flask import (
    flash, g, jsonify, redirect, render_template_string,
    request, session, url_for,
)

logger = logging.getLogger(__name__)


# ============================================================
# APAi Subscriber Detection
# ============================================================

def _detect_apai_subscriber(email):
    """
    Check if an email belongs to a MYSTES user with an APAi/B2B subscription.

    Returns:
        dict: {is_subscriber, mystes_user_id, template_config} or {is_subscriber: False}
    """
    try:
        from models import db, User, CommercialAccount
        user = User.query.filter(
            db.func.lower(User.email) == email.lower()
        ).first()
        if not user:
            return {"is_subscriber": False}

        account = CommercialAccount.query.filter_by(
            owner_user_id=user.id, is_active=True
        ).first()
        if not account or account.subscription_status not in ("active", "trialing"):
            return {"is_subscriber": False}

        template_config = json.dumps({
            "agency_name": account.name,
            "account_id": account.account_id,
            "tier": account.current_tier,
            "subscription_plan": account.subscription_plan,
            "fee_percent": account.fee_percent,
            "referral_code": account.referral_code,
            "total_tickets": account.total_tickets,
        })

        return {
            "is_subscriber": True,
            "mystes_user_id": user.id,
            "template_config": template_config,
        }
    except Exception as e:
        logger.debug("APAi subscriber detection failed for %s: %s", email, e)
        return {"is_subscriber": False}


# ============================================================
# Auth Decorator
# ============================================================

def _get_dev_portal_account():
    """Get current admin portal account from session or API key."""
    from models import DevPortalAccount, DevPortalKey

    # Check session first
    account_id = session.get("dev_portal_account_id")
    if account_id:
        return DevPortalAccount.query.get(account_id)

    # Check API key header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer dpt_"):
        key_string = auth_header[7:]  # Remove "Bearer "
        prefix = key_string[:8]
        candidates = DevPortalKey.query.filter_by(
            key_prefix=prefix, is_active=True
        ).all()
        for candidate in candidates:
            if bcrypt.checkpw(
                key_string.encode("utf-8"),
                candidate.key_hash.encode("utf-8"),
            ):
                candidate.last_used_at = datetime.now(timezone.utc)
                candidate.total_requests += 1
                from models import db
                db.session.commit()
                return candidate.account

    return None


def dev_portal_login_required(f):
    """Decorator: require authenticated admin portal account."""
    @wraps(f)
    def decorated(*args, **kwargs):
        account = _get_dev_portal_account()
        if not account:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            flash("Please log in to access the admin portal.", "error")
            return redirect("/apai/admin/login")
        if not account.is_active:
            return jsonify({"error": "Account suspended"}), 403
        g.dev_portal_account = account
        return f(*args, **kwargs)
    return decorated


def _get_admin_account(member_account):
    """Get the admin (subscriber) account for a team member."""
    if member_account.role == 'admin':
        return member_account
    from models import DevPortalAccount
    return DevPortalAccount.query.filter_by(
        commercial_account_id=member_account.commercial_account_id,
        role='admin',
    ).first()


# ============================================================
# Inline Templates
# ============================================================

ADMIN_AUTH_CONTENT = """
<div class="apai-login-wrap">
    <div class="mystes-page-header text-center">
        <h1>APAi Admin Portal</h1>
        <p>Log in to your team workspace</p>
    </div>

    {% for cat, msg in get_flashed_messages(with_categories=true) %}
    <div class="alert alert-{{ cat }} mb-md">{{ msg }}</div>
    {% endfor %}

    <form method="POST" class="flex flex-col gap-md">
        <input type="email" name="email" placeholder="Email address" required
            class="mystes-input">
        <input type="password" name="password" placeholder="Password" required minlength="8"
            class="mystes-input">
        <button type="submit" class="mystes-btn mystes-btn-primary mystes-btn-lg mystes-btn-full mt-sm">
            Log In
        </button>
    </form>

    <p class="text-center mt-md apai-login-footer">
        Need an APAi subscription? <a href="/apai" class="apai-link">Learn more</a>
    </p>
</div>

<style>
.apai-login-wrap { max-width: 420px; margin: 80px auto; padding: 0 20px; }
.apai-login-footer { color: var(--text-muted); font-size: 0.85rem; }
.apai-link { color: var(--accent); text-decoration: none; }
.apai-link:hover { text-decoration: underline; }
</style>
"""

ADMIN_TERMINAL_CONTENT = """
<div class="term-layout">
    <!-- Sidebar -->
    <div id="devSidebar" class="term-sidebar">
        <div class="term-sidebar-header flex-between">
            <span class="term-sidebar-title">Conversations</span>
            <button onclick="newConversation()" class="mystes-btn mystes-btn-ghost mystes-btn-sm">+ New</button>
        </div>
        <div id="convList" class="term-conv-list"></div>
        <div class="term-sidebar-footer">
            <div><span class="term-tier-label">{{ account.billing_tier|upper }}</span> &middot; {{ usage.queries_used }}/{{ usage.queries_included or '&infin;' }} queries</div>
            <a href="/apai/admin" class="apai-link term-footer-link">Dashboard</a>
            &middot; <a href="/apai/admin/api-keys" class="term-footer-link-muted">API Keys</a>
            &middot; <a href="/apai/admin/logout" class="term-footer-link-muted">Logout</a>
        </div>
    </div>

    <!-- Chat Area -->
    <div class="term-chat-area">
        <div id="devMessages" class="term-messages"></div>
        <div class="term-input-bar">
            <div class="term-input-row">
                <textarea id="devInput" rows="1" placeholder="Ask ANASTASiA anything..."
                    class="mystes-textarea term-chat-input"
                    onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendDevMessage()}"
                    oninput="this.style.height='auto';this.style.height=Math.min(this.scrollHeight,150)+'px'"></textarea>
                <button onclick="sendDevMessage()" id="devSendBtn"
                    class="mystes-btn mystes-btn-primary term-send-btn">
                    <i class="fas fa-paper-plane"></i>
                </button>
            </div>
        </div>
    </div>
</div>

<script>
let _devConvId = null;
let _devSending = false;

function newConversation() {
    _devConvId = null;
    document.getElementById('devMessages').innerHTML = `
        <div class="term-welcome">
            <div class="term-welcome-icon">&#128640;</div>
            <h2 class="term-welcome-title">ANASTASiA Terminal</h2>
            <p class="term-welcome-sub">Build anything on your turnkey OTA.</p>
        </div>`;
    document.getElementById('devInput').focus();
}

function appendDevMessage(role, content) {
    const el = document.getElementById('devMessages');
    const isUser = role === 'user';
    const div = document.createElement('div');
    div.className = 'term-msg-row' + (isUser ? ' term-msg-user' : '');
    const bubble = document.createElement('div');
    bubble.className = isUser ? 'term-bubble term-bubble-user' : 'term-bubble term-bubble-ai';
    if (!isUser) {
        let html = content
            .replace(/```(\\w*)\\n([\\s\\S]*?)```/g, '<pre class="term-code-block"><code>$2</code></pre>')
            .replace(/`([^`]+)`/g, '<code class="term-inline-code">$1</code>')
            .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
            .replace(/\\n/g, '<br>');
        bubble.innerHTML = html;
    } else {
        bubble.textContent = content;
    }
    div.appendChild(bubble);
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
}

function showTyping() {
    const el = document.getElementById('devMessages');
    const div = document.createElement('div');
    div.id = 'devTyping';
    div.className = 'term-msg-row';
    div.innerHTML = '<div class="term-typing-dots">' +
        '<span class="term-dot"></span>' +
        '<span class="term-dot" style="animation-delay:0.2s"></span>' +
        '<span class="term-dot" style="animation-delay:0.4s"></span></div>';
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
}

function hideTyping() {
    const t = document.getElementById('devTyping');
    if (t) t.remove();
}

async function sendDevMessage() {
    if (_devSending) return;
    const input = document.getElementById('devInput');
    const text = input.value.trim();
    if (!text) return;

    _devSending = true;
    input.value = '';
    input.style.height = 'auto';
    document.getElementById('devSendBtn').disabled = true;

    appendDevMessage('user', text);
    showTyping();

    try {
        const resp = await fetch('/api/apai/admin/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({message: text, conversation_id: _devConvId}),
        });
        const data = await resp.json();
        hideTyping();

        if (data.error) {
            appendDevMessage('assistant', 'Error: ' + data.error);
        } else {
            _devConvId = data.conversation_id;
            appendDevMessage('assistant', data.response.content);
        }
    } catch (e) {
        hideTyping();
        appendDevMessage('assistant', 'Connection error. Please try again.');
    }

    _devSending = false;
    document.getElementById('devSendBtn').disabled = false;
    input.focus();
    loadConversations();
}

async function loadConversations() {
    try {
        const resp = await fetch('/api/apai/admin/conversations', {credentials: 'same-origin'});
        const data = await resp.json();
        const list = document.getElementById('convList');
        if (!data.conversations) return;
        list.innerHTML = data.conversations.map(c =>
            `<div onclick="loadConversation('${c.conversation_id}')"
                class="term-conv-item ${_devConvId === c.conversation_id ? 'active' : ''}"
                onmouseover="if('${c.conversation_id}'!==(''+_devConvId))this.style.background='rgba(255,255,255,0.03)'"
                onmouseout="if('${c.conversation_id}'!==(''+_devConvId))this.style.background='transparent'">
                <div class="term-conv-title">${c.title || 'New conversation'}</div>
                <div class="term-conv-meta">${c.message_count} messages</div>
            </div>`
        ).join('');
    } catch(e) {}
}

async function loadConversation(convId) {
    _devConvId = convId;
    const el = document.getElementById('devMessages');
    el.innerHTML = '';
    try {
        const resp = await fetch('/api/apai/admin/conversations/' + convId, {credentials: 'same-origin'});
        const data = await resp.json();
        if (data.messages) {
            data.messages.forEach(m => appendDevMessage(m.role, m.content));
        }
    } catch(e) {}
    loadConversations();
}

document.addEventListener('DOMContentLoaded', () => {
    newConversation();
    loadConversations();
});
</script>

<style>
/* Terminal layout */
.term-layout { display: flex; height: calc(100vh - 60px); overflow: hidden; }

/* Sidebar */
.term-sidebar { width: 260px; background: rgba(0,0,0,0.3); border-right: 1px solid var(--glass-border); display: flex; flex-direction: column; flex-shrink: 0; }
.term-sidebar-header { padding: 16px; border-bottom: 1px solid var(--glass-border); }
.term-sidebar-title { color: var(--accent); font-family: 'Space Grotesk', sans-serif; font-size: 0.9rem; }
.term-conv-list { flex: 1; overflow-y: auto; padding: 8px; }
.term-sidebar-footer { padding: 12px; border-top: 1px solid var(--glass-border); font-size: 0.8rem; color: var(--text-muted); }
.term-tier-label { color: var(--accent); }
.term-footer-link { font-size: 0.75rem; }
.term-footer-link-muted { color: var(--text-muted); text-decoration: none; font-size: 0.75rem; }
.term-footer-link-muted:hover { color: var(--accent); }

/* Conversation list items */
.term-conv-item { padding: 10px 12px; border-radius: var(--radius-md); cursor: pointer; margin-bottom: 4px; border: 1px solid transparent; transition: background 0.15s; }
.term-conv-item.active { background: rgba(179,136,255,0.1); border-color: rgba(179,136,255,0.2); }
.term-conv-title { color: #e8dcc8; font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.term-conv-meta { color: #666; font-size: 0.7rem; }

/* Chat area */
.term-chat-area { flex: 1; display: flex; flex-direction: column; }
.term-messages { flex: 1; overflow-y: auto; padding: 24px; }
.term-input-bar { padding: 16px 24px; border-top: 1px solid var(--glass-border); }
.term-input-row { display: flex; gap: 10px; max-width: 800px; margin: 0 auto; }
.term-chat-input { flex: 1; resize: none; max-height: 150px; border-radius: var(--radius-lg) !important; }
.term-send-btn { padding: 0 20px; border-radius: var(--radius-lg); font-size: 1.1rem; flex-shrink: 0; }

/* Message bubbles */
.term-msg-row { max-width: 800px; margin: 0 auto 16px; display: flex; }
.term-msg-user { justify-content: flex-end; }
.term-bubble { max-width: 85%; padding: 14px 18px; border-radius: var(--radius-lg); font-size: 0.95rem; line-height: 1.6; font-family: var(--font-body); }
.term-bubble-user { background: rgba(179,136,255,0.15); border: 1px solid rgba(179,136,255,0.25); color: #e8dcc8; }
.term-bubble-ai { background: var(--glass-bg); border: 1px solid var(--glass-border); color: #d0c8bc; }

/* Code in chat */
.term-code-block { background: rgba(0,0,0,0.4); padding: 12px; border-radius: var(--radius-md); overflow-x: auto; margin: 8px 0; font-size: 0.85rem; }
.term-inline-code { background: rgba(179,136,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 0.88rem; }

/* Typing indicator */
.term-typing-dots { display: inline-flex; gap: 4px; padding: 14px 18px; background: var(--glass-bg); border: 1px solid var(--glass-border); border-radius: var(--radius-lg); }
.term-dot { width: 8px; height: 8px; background: var(--accent); border-radius: var(--radius-full); animation: dotPulse 1.2s infinite; }
@keyframes dotPulse {
    0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
    40% { opacity: 1; transform: scale(1); }
}

/* Welcome screen */
.term-welcome { text-align: center; padding: 80px 20px; }
.term-welcome-icon { font-size: 2.5rem; margin-bottom: 16px; }
.term-welcome-title { font-family: 'Space Grotesk', sans-serif; color: var(--accent); margin-bottom: 8px; }
.term-welcome-sub { color: var(--text-muted); font-size: 0.95rem; }
</style>
"""


# ============================================================
# Route Registration
# ============================================================

def register_devportal_routes(app, csrf, limiter):
    """Register APAi admin portal routes (repurposed from Dev Portal)."""

    from server import BASE_TEMPLATE

    # ------------------------------------------------------------------
    # Dashboard (NEW — Build #194)
    # ------------------------------------------------------------------

    @app.route("/apai/admin")
    @dev_portal_login_required
    def apai_admin_dashboard():
        """APAi admin dashboard — team management + usage overview."""
        from models import DevPortalAccount
        from dev_portal_billing import get_usage_stats
        account = g.dev_portal_account
        admin = _get_admin_account(account)
        usage = get_usage_stats(account, admin)

        # Get team members (only visible to admin)
        team_members = []
        if account.role == 'admin' and account.commercial_account_id:
            members = DevPortalAccount.query.filter_by(
                commercial_account_id=account.commercial_account_id,
                is_active=True,
            ).order_by(DevPortalAccount.created_at.asc()).all()
            team_members = [m.to_dict() for m in members]

        # Per-member usage breakdown
        total_team_queries = sum(m.get('queries_used', 0) for m in team_members)
        team_html = ""
        for m in team_members:
            role_badge = '<span class="mystes-badge mystes-badge-purple">ADMIN</span>' if m['role'] == 'admin' else '<span class="dash-member-role">Member</span>'
            member_queries = m.get('queries_used', 0)
            limit_val = m.get('query_limit')
            limit_text = str(limit_val) if limit_val else "Unlimited"
            bar_max = limit_val or usage.get('queries_included', 500) or 500
            bar_pct = min(100, int((member_queries / bar_max) * 100)) if bar_max > 0 else 0
            bar_color = "#22c55e" if bar_pct < 70 else ("#f59e0b" if bar_pct < 90 else "#ef4444")
            remove_btn = "" if m['role'] == 'admin' else f"""<button onclick="removeMember('{m['account_id']}')" class="mystes-btn mystes-btn-danger mystes-btn-sm">Remove</button>"""
            team_html += f"""
            <div class="mystes-card compact mb-sm">
                <div class="flex-between mb-sm">
                    <div>
                        <div class="dash-member-name">{m.get('name') or m['email']} {role_badge}</div>
                        <div class="dash-member-email">{m['email']}</div>
                    </div>
                    {remove_btn}
                </div>
                <div class="dash-progress-row">
                    <div class="dash-progress-track">
                        <div class="dash-progress-fill" style="width:{bar_pct}%;background:{bar_color};"></div>
                    </div>
                    <div class="dash-progress-label">{member_queries} / {limit_text}</div>
                </div>
            </div>"""

        admin_section = ""
        if account.role == 'admin':
            admin_section = f"""
            <div class="mb-lg">
                <h2 class="dash-section-title">Team Members</h2>
                <form id="addMemberForm" class="dash-invite-form mb-md">
                    <input type="email" id="memberEmail" placeholder="team@example.com" required
                        class="mystes-input" style="flex:1;">
                    <input type="text" id="memberName" placeholder="Name (optional)"
                        class="mystes-input" style="width:160px;">
                    <button type="submit" class="mystes-btn mystes-btn-primary">Invite</button>
                </form>
                {team_html}
            </div>"""

        content = f"""
        <div class="mystes-page" style="padding-top:50px;">
            <div class="flex-between mb-lg">
                <h1 class="dash-title">APAi Admin</h1>
                <a href="/apai/admin/terminal" class="mystes-btn mystes-btn-primary">
                    Open Terminal
                </a>
            </div>

            <div class="dash-stats-grid mb-lg">
                <div class="mystes-card compact">
                    <div class="dash-stat-label">Tier</div>
                    <div class="dash-stat-value dash-stat-accent">{usage.get('tier', 'pro').upper()}</div>
                </div>
                <div class="mystes-card compact">
                    <div class="dash-stat-label">Queries Used</div>
                    <div class="dash-stat-value">{usage.get('queries_used', 0)} / {usage.get('queries_included', 0)}</div>
                </div>
                <div class="mystes-card compact">
                    <div class="dash-stat-label">Overage</div>
                    <div class="dash-stat-value">{usage.get('overage_queries', 0)}</div>
                </div>
                <div class="mystes-card compact">
                    <div class="dash-stat-label">Est. Cost</div>
                    <div class="dash-stat-value">${{usage.get('estimated_cost_usd', 0):.2f}}</div>
                </div>
                <div class="mystes-card compact">
                    <div class="dash-stat-label">Team Size</div>
                    <div class="dash-stat-value">{len(team_members)}</div>
                </div>
            </div>

            {admin_section}

            <div class="dash-nav-links">
                <a href="/apai/admin/terminal" class="apai-link">Terminal</a>
                <a href="/apai/admin/api-keys" class="dash-nav-muted">API Keys</a>
                <a href="/apai/admin/logout" class="dash-nav-muted">Logout</a>
            </div>
        </div>

        <style>
        .dash-title {{ font-family: 'Space Grotesk', sans-serif; font-size: 2rem; color: var(--accent); }}
        .dash-section-title {{ font-family: 'Space Grotesk', sans-serif; font-size: 1.3rem; color: var(--accent); margin-bottom: 16px; }}
        .dash-stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; }}
        .dash-stat-label {{ color: var(--text-muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; }}
        .dash-stat-value {{ color: #e8dcc8; font-size: 1.4rem; font-weight: 700; }}
        .dash-stat-accent {{ color: var(--accent); }}
        .dash-invite-form {{ display: flex; gap: 10px; }}
        .dash-member-name {{ color: #e8dcc8; font-size: 0.9rem; }}
        .dash-member-email {{ color: var(--text-muted); font-size: 0.8rem; }}
        .dash-member-role {{ color: var(--text-muted); font-size: 0.7rem; }}
        .dash-progress-row {{ display: flex; align-items: center; gap: 12px; }}
        .dash-progress-track {{ flex: 1; background: rgba(255,255,255,0.06); border-radius: 4px; height: 6px; overflow: hidden; }}
        .dash-progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.3s; }}
        .dash-progress-label {{ color: var(--text-muted); font-size: 0.75rem; white-space: nowrap; }}
        .dash-nav-links {{ display: flex; gap: 12px; }}
        .dash-nav-muted {{ color: var(--text-muted); text-decoration: none; font-size: 0.9rem; }}
        .dash-nav-muted:hover {{ color: var(--accent); }}
        </style>

        <script>
        document.getElementById('addMemberForm')?.addEventListener('submit', async function(e) {{
            e.preventDefault();
            const email = document.getElementById('memberEmail').value;
            const name = document.getElementById('memberName').value;
            const btn = this.querySelector('button[type=submit]');
            btn.disabled = true; btn.textContent = 'Inviting...';
            const resp = await fetch('/api/apai/admin/team', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                credentials: 'same-origin',
                body: JSON.stringify({{email, name}}),
            }});
            const data = await resp.json();
            if (data.error) {{ alert(data.error); btn.disabled = false; btn.textContent = 'Invite'; }}
            else {{ alert('Invitation sent to ' + email); location.reload(); }}
        }});

        async function removeMember(accountId) {{
            if (!confirm('Remove this team member?')) return;
            await fetch('/api/apai/admin/team/' + accountId, {{method: 'DELETE', credentials: 'same-origin'}});
            location.reload();
        }}
        </script>
        """

        return render_template_string(
            BASE_TEMPLATE, title="APAi Admin — Dashboard",
            content=render_template_string(content, usage=usage),
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @app.route("/apai/admin/login", methods=["GET", "POST"])
    def apai_admin_login():
        """APAi admin portal login."""
        if session.get("dev_portal_account_id"):
            return redirect("/apai/admin")

        if request.method == "GET":
            return render_template_string(
                BASE_TEMPLATE, title="Log In — APAi Admin",
                content=render_template_string(ADMIN_AUTH_CONTENT),
            )

        # POST — authenticate
        from models import DevPortalAccount
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        account = DevPortalAccount.query.filter_by(email=email).first()
        if not account or not account.check_password(password):
            flash("Invalid email or password.", "error")
            return redirect("/apai/admin/login")

        if not account.is_active:
            flash("This account has been suspended.", "error")
            return redirect("/apai/admin/login")

        from models import db
        session["dev_portal_account_id"] = account.id
        account.last_login = datetime.now(timezone.utc)
        db.session.commit()

        return redirect("/apai/admin")

    @app.route("/apai/admin/logout")
    def apai_admin_logout():
        """APAi admin portal logout."""
        session.pop("dev_portal_account_id", None)
        return redirect("/apai/admin/login")

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    @app.route("/apai/admin/terminal")
    @dev_portal_login_required
    def apai_admin_terminal():
        """ANASTASiA terminal — the dev workspace."""
        from dev_portal_billing import get_usage_stats
        account = g.dev_portal_account
        admin = _get_admin_account(account)
        usage = get_usage_stats(account, admin)

        return render_template_string(
            BASE_TEMPLATE, title="Terminal — ANASTASiA",
            content=render_template_string(ADMIN_TERMINAL_CONTENT,
                account=admin or account, usage=usage,
            ),
        )

    # ------------------------------------------------------------------
    # Chat API
    # ------------------------------------------------------------------

    @app.route("/api/apai/admin/chat", methods=["POST"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_chat():
        """APAi admin portal chat endpoint."""
        from models import db, DevPortalConversation, DevPortalMessage
        from dev_portal_ai import DevPortalAI
        from dev_portal_billing import check_quota, record_query_usage

        account = g.dev_portal_account
        admin = _get_admin_account(account)
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()

        if not message:
            return jsonify({"error": "Message required"}), 400

        # Quota check against subscriber's pool
        quota = check_quota(account, admin)
        if not quota["allowed"]:
            return jsonify({"error": quota.get("error", "Quota exceeded"), "quota": quota}), 402

        # Get or create conversation
        conversation_id = data.get("conversation_id")
        if conversation_id:
            conv = DevPortalConversation.query.filter_by(
                conversation_id=conversation_id,
                account_id=account.id,
                is_active=True,
            ).first()
        else:
            conv = None

        if not conv:
            conversation_id = f"dpc_{secrets.token_hex(12)}"
            conv = DevPortalConversation(
                conversation_id=conversation_id,
                account_id=account.id,
                title=message[:80] if message else "New conversation",
            )
            db.session.add(conv)
            db.session.commit()

        # Load conversation history (last 50 messages)
        history = DevPortalMessage.query.filter_by(
            conversation_id=conversation_id
        ).order_by(DevPortalMessage.created_at.asc()).limit(50).all()

        messages_history = [{"role": m.role, "content": m.content} for m in history]

        # Build APAi context from subscriber
        apai_context = None
        config_account = admin or account
        if config_account.apai_template_config:
            apai_context = {"template_config": config_account.apai_template_config}

        # Call AI engine
        engine = DevPortalAI()
        result = engine.chat(
            messages_history=messages_history,
            user_message=message,
            apai_context=apai_context,
        )

        # Persist messages
        user_msg = DevPortalMessage(
            conversation_id=conversation_id,
            role="user",
            content=message,
        )
        assistant_msg = DevPortalMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=result["content"],
            tokens_used=result.get("tokens_used", 0),
            model_used=result.get("model_used", ""),
            response_time_ms=result.get("response_time_ms", 0),
        )
        db.session.add(user_msg)
        db.session.add(assistant_msg)

        conv.message_count += 2
        conv.total_tokens_used += result.get("tokens_used", 0)
        conv.last_message_at = datetime.now(timezone.utc)

        # Record usage — increments member + admin counters
        record_query_usage(account, admin)

        db.session.commit()

        return jsonify({
            "conversation_id": conversation_id,
            "response": result,
            "usage": {
                "queries_used": (admin or account).queries_used_this_period,
                "queries_included": (admin or account).queries_included,
                "tier": (admin or account).billing_tier,
            },
        })

    # ------------------------------------------------------------------
    # Conversations API
    # ------------------------------------------------------------------

    @app.route("/api/apai/admin/conversations", methods=["GET"])
    @dev_portal_login_required
    def apai_admin_list_conversations():
        """List conversations."""
        from models import DevPortalConversation
        account = g.dev_portal_account
        convs = DevPortalConversation.query.filter_by(
            account_id=account.id, is_active=True
        ).order_by(DevPortalConversation.last_message_at.desc()).limit(50).all()

        return jsonify({
            "conversations": [{
                "conversation_id": c.conversation_id,
                "title": c.title,
                "message_count": c.message_count,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            } for c in convs],
        })

    @app.route("/api/apai/admin/conversations", methods=["POST"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_create_conversation():
        """Create new conversation."""
        from models import db, DevPortalConversation
        account = g.dev_portal_account
        data = request.get_json(silent=True) or {}

        conv = DevPortalConversation(
            conversation_id=f"dpc_{secrets.token_hex(12)}",
            account_id=account.id,
            title=data.get("title", "New conversation"),
        )
        db.session.add(conv)
        db.session.commit()

        return jsonify({
            "conversation_id": conv.conversation_id,
            "title": conv.title,
        })

    @app.route("/api/apai/admin/conversations/<conv_id>", methods=["GET"])
    @dev_portal_login_required
    def apai_admin_get_conversation(conv_id):
        """Get conversation with messages."""
        from models import DevPortalConversation, DevPortalMessage
        account = g.dev_portal_account

        conv = DevPortalConversation.query.filter_by(
            conversation_id=conv_id,
            account_id=account.id,
            is_active=True,
        ).first()
        if not conv:
            return jsonify({"error": "Conversation not found"}), 404

        messages = DevPortalMessage.query.filter_by(
            conversation_id=conv_id
        ).order_by(DevPortalMessage.created_at.asc()).all()

        return jsonify({
            "conversation_id": conv.conversation_id,
            "title": conv.title,
            "messages": [{
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            } for m in messages],
        })

    @app.route("/api/apai/admin/conversations/<conv_id>", methods=["DELETE"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_delete_conversation(conv_id):
        """Soft-delete a conversation."""
        from models import db, DevPortalConversation
        account = g.dev_portal_account

        conv = DevPortalConversation.query.filter_by(
            conversation_id=conv_id,
            account_id=account.id,
        ).first()
        if not conv:
            return jsonify({"error": "Conversation not found"}), 404

        conv.is_active = False
        db.session.commit()
        return jsonify({"deleted": True})

    # ------------------------------------------------------------------
    # Usage API
    # ------------------------------------------------------------------

    @app.route("/api/apai/admin/usage")
    @dev_portal_login_required
    def apai_admin_usage():
        """Get detailed usage stats."""
        from dev_portal_billing import get_usage_stats
        account = g.dev_portal_account
        admin = _get_admin_account(account)
        return jsonify(get_usage_stats(account, admin))

    # ------------------------------------------------------------------
    # Account Info
    # ------------------------------------------------------------------

    @app.route("/api/apai/admin/account")
    @dev_portal_login_required
    def apai_admin_account_info():
        """Get admin portal account info."""
        account = g.dev_portal_account
        return jsonify({
            "account_id": account.account_id,
            "email": account.email,
            "name": account.name,
            "company": account.company,
            "role": account.role,
            "billing_tier": account.billing_tier,
            "apai_subscriber": account.apai_subscriber,
            "is_active": account.is_active,
            "created_at": account.created_at.isoformat() if account.created_at else None,
        })

    # ------------------------------------------------------------------
    # Team Management (NEW — Build #194)
    # ------------------------------------------------------------------

    @app.route("/api/apai/admin/team", methods=["POST"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_add_team_member():
        """Add a team member with auto-generated temp password + invitation email."""
        from models import db, DevPortalAccount
        from email_service import send_team_invitation_email
        account = g.dev_portal_account

        if account.role != 'admin':
            return jsonify({"error": "Only admins can add team members"}), 403

        data = request.get_json(silent=True) or {}
        email = data.get("email", "").strip().lower()
        name = data.get("name", "").strip() or None
        query_limit = data.get("query_limit")

        if not email:
            return jsonify({"error": "Email required"}), 400

        # Check for duplicate email
        existing = DevPortalAccount.query.filter_by(email=email).first()
        if existing:
            return jsonify({"error": "An account with this email already exists"}), 409

        # Generate temp password and invitation token
        temp_password = f"Tmp{secrets.token_hex(4)}!"
        invitation_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)

        member = DevPortalAccount(
            account_id=f"dpa_{secrets.token_hex(12)}",
            email=email,
            name=name,
            role='member',
            commercial_account_id=account.commercial_account_id,
            added_by_id=account.id,
            billing_tier=account.billing_tier,
            apai_subscriber=True,
            apai_template_config=account.apai_template_config,
            query_limit=int(query_limit) if query_limit else None,
            is_active=True,
            is_verified=True,
            invitation_token=invitation_token,
            invitation_sent_at=now,
        )
        member.set_password(temp_password)
        db.session.add(member)
        db.session.commit()

        # Send invitation email (fire-and-forget)
        send_team_invitation_email(
            to=email,
            name=name,
            inviter_name=account.name or account.email,
            temp_password=temp_password,
            company=account.company,
        )

        logger.info("Team member invited: %s by %s", email, account.account_id)

        return jsonify({
            "added": True,
            "invitation_sent": True,
            "member": member.to_dict(),
        })

    @app.route("/api/apai/admin/team/<account_id>", methods=["DELETE"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_remove_team_member(account_id):
        """Remove a team member. Admin only."""
        from models import db, DevPortalAccount
        account = g.dev_portal_account

        if account.role != 'admin':
            return jsonify({"error": "Only admins can remove team members"}), 403

        member = DevPortalAccount.query.filter_by(
            account_id=account_id,
            commercial_account_id=account.commercial_account_id,
        ).first()
        if not member:
            return jsonify({"error": "Team member not found"}), 404

        if member.role == 'admin':
            return jsonify({"error": "Cannot remove the admin account"}), 400

        member.is_active = False
        db.session.commit()

        logger.info("Team member removed: %s by %s", account_id, account.account_id)
        return jsonify({"removed": True})

    @app.route("/api/apai/admin/team/<account_id>", methods=["PUT"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_update_team_member(account_id):
        """Update a team member (e.g. query limit). Admin only."""
        from models import db, DevPortalAccount
        account = g.dev_portal_account

        if account.role != 'admin':
            return jsonify({"error": "Only admins can update team members"}), 403

        member = DevPortalAccount.query.filter_by(
            account_id=account_id,
            commercial_account_id=account.commercial_account_id,
        ).first()
        if not member:
            return jsonify({"error": "Team member not found"}), 404

        data = request.get_json(silent=True) or {}
        if "query_limit" in data:
            member.query_limit = int(data["query_limit"]) if data["query_limit"] else None
        if "name" in data:
            member.name = data["name"]

        db.session.commit()
        return jsonify({"updated": True, "member": member.to_dict()})

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    @app.route("/apai/admin/api-keys", methods=["GET"])
    @dev_portal_login_required
    def apai_admin_api_keys_page():
        """API key management page."""
        account = g.dev_portal_account
        keys = account.api_keys.filter_by(is_active=True).all()

        key_list_html = ""
        for k in keys:
            key_list_html += f"""
            <div class="mystes-card compact flex-between mb-sm">
                <div>
                    <div class="keys-prefix">{k.key_prefix}...</div>
                    <div class="keys-meta">{k.label} &middot; {k.total_requests} requests</div>
                </div>
                <button onclick="revokeKey({k.id})" class="mystes-btn mystes-btn-danger mystes-btn-sm">Revoke</button>
            </div>"""

        content = f"""
        <div class="mystes-page keys-page">
            <div class="mystes-page-header">
                <h1>API Keys</h1>
                <p>Use API keys for programmatic access to the ANASTASiA chat API.</p>
            </div>

            {{% for cat, msg in get_flashed_messages(with_categories=true) %}}
            <div class="alert alert-success mb-md">{{{{ msg }}}}</div>
            {{% endfor %}}

            <form method="POST" class="keys-gen-form mb-lg">
                <input type="text" name="label" placeholder="Key label (e.g. Production)" value="Default"
                    class="mystes-input" style="flex:1;">
                <button type="submit" class="mystes-btn mystes-btn-primary">Generate</button>
            </form>

            {key_list_html}

            <div class="mt-md">
                <a href="/apai/admin" class="apai-link">&larr; Back to Dashboard</a>
            </div>

            <style>
            .keys-page {{ max-width: 600px; padding-top: 50px; }}
            .keys-gen-form {{ display: flex; gap: 10px; }}
            .keys-prefix {{ color: #e8dcc8; font-family: monospace; font-size: 0.9rem; }}
            .keys-meta {{ color: var(--text-muted); font-size: 0.8rem; }}
            .apai-link {{ color: var(--accent); text-decoration: none; font-size: 0.9rem; }}
            .apai-link:hover {{ text-decoration: underline; }}
            </style>

            <script>
            async function revokeKey(keyId) {{
                if (!confirm('Revoke this API key?')) return;
                await fetch('/api/apai/admin/api-keys/' + keyId, {{method: 'DELETE', credentials: 'same-origin'}});
                location.reload();
            }}
            </script>
        </div>"""

        return render_template_string(
            BASE_TEMPLATE, title="API Keys — APAi Admin",
            content=render_template_string(content),
        )

    @app.route("/apai/admin/api-keys", methods=["POST"])
    @dev_portal_login_required
    def apai_admin_generate_api_key():
        """Generate a new dpt_ API key."""
        from models import db, DevPortalKey
        account = g.dev_portal_account
        label = request.form.get("label", "Default").strip()

        raw_key = f"dpt_{secrets.token_hex(24)}"
        key_hash = bcrypt.hashpw(
            raw_key.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        key = DevPortalKey(
            account_id=account.id,
            key_prefix=raw_key[:8],
            key_hash=key_hash,
            label=label,
        )
        db.session.add(key)
        db.session.commit()

        flash(f"API key generated: {raw_key} — save this, it won't be shown again!", "success")
        return redirect("/apai/admin/api-keys")

    @app.route("/api/apai/admin/api-keys/<int:key_id>", methods=["DELETE"])
    @csrf.exempt
    @dev_portal_login_required
    def apai_admin_revoke_api_key(key_id):
        """Revoke an API key."""
        from models import db, DevPortalKey
        account = g.dev_portal_account

        key = DevPortalKey.query.filter_by(
            id=key_id, account_id=account.id
        ).first()
        if not key:
            return jsonify({"error": "Key not found"}), 404

        key.is_active = False
        db.session.commit()
        return jsonify({"revoked": True})

    # ------------------------------------------------------------------
    # Legacy redirects (old /dev/* URLs → new /apai/admin/*)
    # ------------------------------------------------------------------

    @app.route("/dev")
    @app.route("/dev/login")
    @app.route("/dev/signup")
    @app.route("/dev/pricing")
    def dev_legacy_redirect():
        """Redirect old Dev Portal URLs to APAi admin portal."""
        return redirect("/apai/admin/login", code=301)

    @app.route("/dev/terminal")
    def dev_terminal_redirect():
        """Redirect old terminal URL."""
        return redirect("/apai/admin/terminal", code=301)

    @app.route("/dev/logout")
    def dev_logout_redirect():
        """Redirect old logout URL."""
        return redirect("/apai/admin/logout", code=301)
