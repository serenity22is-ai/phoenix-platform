"""
MYSTES Collections / Wishlist Routes — Save flights, hotels, and more.

Build #167: Airbnb-style wishlist with shareable collections across all verticals.

Routes:
    GET    /collections                              — List user's collections
    POST   /api/collections                          — Create collection
    GET    /collections/<id>                          — Collection detail (owner)
    GET    /c/<slug>                                  — Public shared collection
    PUT    /api/collections/<id>                      — Update collection (name, sharing)
    DELETE /api/collections/<id>                      — Delete collection
    POST   /api/collections/<id>/items                — Save item to collection
    DELETE /api/collections/<id>/items/<item_id>       — Remove item
    POST   /api/save-item                             — Quick-save to Favorites

Register in server.py:
    from routes_collections import register_collection_routes
    register_collection_routes(app, csrf, limiter)

MYSTES KYRIOS LLC — Confidential.
"""

import json
import logging
import secrets
from datetime import datetime

from flask import request, jsonify, render_template_string, redirect, url_for
from flask_login import current_user, login_required

from models import db, Collection, SavedItem, User

logger = logging.getLogger(__name__)


# ============================================================
# COLLECTIONS LIST — "MY COLLECTIONS" page
# ============================================================

COLLECTIONS_LIST_CONTENT = """
<style>
/* Page-specific: collections layout */
.collections-page { max-width: 960px; margin: 0 auto; padding: 0 16px; }

.collections-page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 40px 0 24px;
    flex-wrap: wrap;
    gap: 16px;
}
.collections-page-header h1 {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 32px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--text-bright, #f5f5f5);
    margin: 0;
}

/* Create form — slide-down panel */
.collections-create-form {
    display: none;
    margin-bottom: 20px;
}
.collections-create-form.visible { display: block; }
.collections-create-form-inner {
    display: flex;
    gap: 12px;
    align-items: end;
}

/* Collection card icon */
.collection-card-icon {
    width: 48px; height: 48px;
    background: rgba(201, 169, 110, 0.1);
    border: 1px solid rgba(201, 169, 110, 0.2);
    border-radius: var(--radius-lg, 12px);
    display: flex; align-items: center; justify-content: center;
    font-size: 22px;
}

/* Hover-reveal delete button */
.collection-card-actions {
    display: flex;
    gap: 4px;
    opacity: 0;
    transition: opacity 0.2s;
}
.mystes-card.interactive:hover .collection-card-actions { opacity: 1; }
.collection-card-delete {
    width: 32px; height: 32px;
    background: rgba(239, 68, 68, 0.08);
    border: 1px solid rgba(239, 68, 68, 0.15);
    border-radius: var(--radius-md, 8px);
    display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    color: var(--danger-red, #ef4444);
    font-size: 14px;
    transition: all 0.2s;
}
.collection-card-delete:hover {
    background: rgba(239, 68, 68, 0.2);
    border-color: rgba(239, 68, 68, 0.4);
}

/* Card content */
.collection-card-name {
    font-family: var(--font-body, 'Outfit', sans-serif);
    font-size: 18px;
    font-weight: 600;
    color: var(--text-bright, #f5f5f5);
    margin: 0 0 6px;
}
.collection-card-meta {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
    color: rgba(255,255,255,0.6);
}

/* Empty state icon override */
.collections-empty-icon {
    font-size: 56px;
    opacity: 0.25;
    margin-bottom: 20px;
}

@media (max-width: 600px) {
    .collections-page-header { flex-direction: column; align-items: flex-start; }
    .collections-create-form-inner { flex-direction: column; }
}
</style>

<div class="collections-page">
    <div class="collections-page-header">
        <h1>MY COLLECTIONS</h1>
        <button class="mystes-btn mystes-btn-gold" onclick="toggleCreateForm()">+ New Collection</button>
    </div>

    <!-- Inline create form -->
    <div class="collections-create-form mystes-card" id="create-form">
        <div class="collections-create-form-inner">
            <div style="flex:1;">
                <label class="mystes-label">Collection Name</label>
                <input type="text" class="mystes-input" id="new-collection-name" placeholder="e.g. Summer Trip, Weekend Getaway..."
                       onkeydown="if(event.key==='Enter') createCollection()">
            </div>
            <button class="mystes-btn mystes-btn-gold" onclick="createCollection()">Create</button>
        </div>
    </div>

    <!-- Collections grid -->
    <div id="collections-container">
        {% if collections %}
        <div class="mystes-grid" style="margin-bottom:40px;">
            {% for c in collections %}
            <div class="mystes-card interactive" style="cursor:pointer;" onclick="window.location.href='/collections/{{ c.id }}'">
                <div class="flex-between" style="margin-bottom:16px;">
                    <div class="collection-card-icon">&#9829;</div>
                    <div class="collection-card-actions">
                        <div class="collection-card-delete" onclick="event.stopPropagation(); deleteCollection({{ c.id }}, '{{ c.name }}')" title="Delete">&#10005;</div>
                    </div>
                </div>
                <h3 class="collection-card-name">{{ c.name }}</h3>
                <div class="collection-card-meta">
                    <span>{{ c.items.count() }} item{{ 's' if c.items.count() != 1 else '' }}</span>
                    {% if c.is_shared %}
                    <span class="mystes-badge-gold">&#128279; Shared</span>
                    {% endif %}
                </div>
            </div>
            {% endfor %}
        </div>
        {% else %}
        <div class="mystes-empty" style="padding:80px 20px;">
            <div class="collections-empty-icon">&#9829;</div>
            <h2 style="font-family:var(--font-brand,'Space Grotesk',sans-serif);font-size:22px;color:var(--text-bright,#f5f5f5);margin:0 0 10px;">No Collections Yet</h2>
            <p style="max-width:400px;margin:0 auto 24px;">Save flights, hotels, and more to collections. Organize your travel finds and share them with others.</p>
            <button class="mystes-btn mystes-btn-gold" onclick="toggleCreateForm()">Create Your First Collection</button>
        </div>
        {% endif %}
    </div>
</div>

<script>
function toggleCreateForm() {
    const form = document.getElementById('create-form');
    form.classList.toggle('visible');
    if (form.classList.contains('visible')) {
        document.getElementById('new-collection-name').focus();
    }
}

async function createCollection() {
    const nameInput = document.getElementById('new-collection-name');
    const name = nameInput.value.trim();
    if (!name) { nameInput.focus(); return; }

    try {
        const resp = await fetch('/api/collections', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name })
        });
        const data = await resp.json();
        if (data.success) {
            window.location.reload();
        } else {
            alert(data.error || 'Failed to create collection');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function deleteCollection(id, name) {
    if (!confirm('Delete "' + name + '"? All saved items in this collection will be removed.')) return;

    try {
        const resp = await fetch('/api/collections/' + id, { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) {
            window.location.reload();
        } else {
            alert(data.error || 'Failed to delete collection');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}
</script>
"""


# ============================================================
# COLLECTION DETAIL — Single collection view with items
# ============================================================

COLLECTION_DETAIL_CONTENT = """
<style>
/* Page-specific: detail layout */
.collection-detail { max-width: 960px; margin: 0 auto; padding: 0 16px; }

.collection-detail-header {
    padding: 40px 0 24px;
}
.collection-detail-back {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: rgba(255,255,255,0.6);
    text-decoration: none;
    font-size: 13px;
    margin-bottom: 16px;
    transition: color 0.2s;
}
.collection-detail-back:hover { color: var(--text-bright, #f5f5f5); }

.collection-detail-title-row {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
    flex-wrap: wrap;
}
.collection-detail-title-row h1 {
    font-family: var(--font-brand, 'Space Grotesk', sans-serif);
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 2px;
    color: var(--text-bright, #f5f5f5);
    margin: 0 0 6px;
}
.collection-detail-meta {
    color: rgba(255,255,255,0.6);
    font-size: 14px;
}

/* Share toggle — page-specific widget */
.share-toggle-row {
    display: flex;
    align-items: center;
    gap: 12px;
}
.share-toggle-label {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-bright, #f5f5f5);
}
.share-toggle {
    position: relative;
    width: 44px; height: 24px;
    cursor: pointer;
}
.share-toggle input { opacity: 0; width: 0; height: 0; }
.share-toggle-track {
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(255,255,255,0.12);
    border-radius: var(--radius-full, 12px);
    transition: background 0.3s;
}
.share-toggle input:checked + .share-toggle-track {
    background: var(--accent, #c9a44a);
}
.share-toggle-knob {
    position: absolute;
    top: 2px; left: 2px;
    width: 20px; height: 20px;
    background: #fff;
    border-radius: 50%;
    transition: transform 0.3s;
    pointer-events: none;
}
.share-toggle input:checked ~ .share-toggle-knob {
    transform: translateX(20px);
}
.share-url-box {
    display: flex;
    align-items: center;
    gap: 8px;
}
.share-url-box input {
    padding: 8px 12px;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: var(--radius-md, 10px);
    color: var(--text-bright, #f5f5f5);
    font-size: 13px;
    font-family: var(--font-body, 'Outfit', sans-serif);
    min-width: 240px;
}

/* Saved item card internals */
.saved-item-top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 12px;
}
.saved-item-vertical-icon {
    width: 40px; height: 40px;
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.15);
    border-radius: var(--radius-md, 10px);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
}
.saved-item-remove {
    width: 28px; height: 28px;
    background: rgba(239, 68, 68, 0.06);
    border: 1px solid rgba(239, 68, 68, 0.12);
    border-radius: var(--radius-md, 8px);
    display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    color: var(--danger-red, #ef4444);
    font-size: 12px;
    opacity: 0;
    transition: all 0.2s;
}
.mystes-card:hover .saved-item-remove { opacity: 1; }
.saved-item-remove:hover {
    background: rgba(239, 68, 68, 0.15);
    border-color: rgba(239, 68, 68, 0.3);
}

.saved-item-vertical-tag {
    display: inline-block;
    padding: 2px 8px;
    background: rgba(201, 169, 110, 0.08);
    border: 1px solid rgba(201, 169, 110, 0.15);
    border-radius: var(--radius-sm, 6px);
    font-size: 11px;
    font-weight: 600;
    color: var(--accent, #c9a44a);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}

.saved-item-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--text-bright, #f5f5f5);
    margin: 0 0 8px;
    line-height: 1.3;
}
.saved-item-subtitle {
    font-size: 13px;
    color: var(--text-muted, #aaa);
    margin-bottom: 12px;
}

/* Price row */
.saved-item-price-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 12px;
    border-top: 1px solid var(--glass-border, rgba(255,255,255,0.06));
    margin-bottom: 12px;
}
.saved-item-price {
    font-size: 20px;
    font-weight: 700;
    color: var(--accent, #c9a44a);
}
.saved-item-price-label {
    font-size: 11px;
    color: rgba(255,255,255,0.6);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.saved-item-price-change {
    font-size: 12px;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: var(--radius-sm, 6px);
}
.saved-item-price-down {
    background: rgba(74, 222, 128, 0.1);
    color: #4ade80;
}
.saved-item-price-up {
    background: rgba(239, 68, 68, 0.1);
    color: var(--danger-red, #ef4444);
}
.saved-item-price-same {
    background: rgba(255,255,255,0.06);
    color: rgba(255,255,255,0.5);
}

/* Empty state icon override */
.collection-empty-icon {
    font-size: 48px;
    opacity: 0.25;
    margin-bottom: 16px;
}

@media (max-width: 600px) {
    .collection-detail-title-row { flex-direction: column; }
    .collection-share-panel { flex-direction: column; align-items: flex-start; }
    .share-url-box { width: 100%; }
    .share-url-box input { flex: 1; min-width: 0; }
}
</style>

<div class="collection-detail">
    <div class="collection-detail-header">
        <a href="/collections" class="collection-detail-back">&larr; All Collections</a>
        <div class="collection-detail-title-row">
            <div>
                <h1>{{ collection.name }}</h1>
                <div class="collection-detail-meta">
                    {{ item_count }} item{{ 's' if item_count != 1 else '' }}
                    &middot; Created {{ collection.created_at.strftime('%b %d, %Y') if collection.created_at else '' }}
                </div>
            </div>
        </div>
    </div>

    {% if not read_only %}
    <!-- Share panel -->
    <div class="mystes-card collection-share-panel flex-between" style="margin-bottom:20px;flex-wrap:wrap;gap:16px;">
        <div class="share-toggle-row">
            <label class="share-toggle">
                <input type="checkbox" id="share-toggle" {{ 'checked' if collection.is_shared else '' }}
                       onchange="toggleShare({{ collection.id }})">
                <span class="share-toggle-track"></span>
                <span class="share-toggle-knob"></span>
            </label>
            <span class="share-toggle-label">Share this collection</span>
        </div>
        <div class="share-url-box" id="share-url-box" style="{{ '' if collection.is_shared else 'display:none;' }}">
            <input type="text" id="share-url" readonly
                   value="{{ share_url }}"
                   onclick="this.select()">
            <button class="mystes-btn mystes-btn-gold mystes-btn-sm" onclick="copyShareLink()">Copy</button>
        </div>
    </div>
    {% endif %}

    <!-- Items grid -->
    {% if items %}
    <div class="mystes-grid" style="margin-bottom:40px;">
        {% for item in items %}
        {% set data = item.item_data_json | default('{}', true) %}
        {% if data is string %}
            {% set parsed = data | tojson | safe %}
        {% else %}
            {% set parsed = data %}
        {% endif %}
        <div class="mystes-card">
            <div class="saved-item-top">
                <div class="saved-item-vertical-icon">
                    {% if item.vertical == 'flight' %}&#9992;{% elif item.vertical == 'hotel' %}&#127960;{% elif item.vertical == 'car' %}&#128663;{% elif item.vertical == 'activity' %}&#127915;{% else %}&#9829;{% endif %}
                </div>
                {% if not read_only %}
                <div class="saved-item-remove" onclick="removeItem({{ collection.id }}, {{ item.id }})" title="Remove">&#10005;</div>
                {% endif %}
            </div>
            <span class="saved-item-vertical-tag">{{ item.vertical }}</span>
            <h3 class="saved-item-title" id="item-title-{{ item.id }}">{{ item.vertical | capitalize }} Deal</h3>
            <div class="saved-item-subtitle" id="item-subtitle-{{ item.id }}"></div>

            <div class="saved-item-price-row">
                <div>
                    <div class="saved-item-price-label">Saved Price</div>
                    <div class="saved-item-price">${{ '%.0f' | format(item.price_at_save or 0) }}</div>
                </div>
                {% if item.current_price and item.price_at_save %}
                    {% if item.current_price < item.price_at_save %}
                    <span class="saved-item-price-change saved-item-price-down">&#9660; ${{ '%.0f' | format(item.price_at_save - item.current_price) }} lower</span>
                    {% elif item.current_price > item.price_at_save %}
                    <span class="saved-item-price-change saved-item-price-up">&#9650; ${{ '%.0f' | format(item.current_price - item.price_at_save) }} higher</span>
                    {% else %}
                    <span class="saved-item-price-change saved-item-price-same">Same price</span>
                    {% endif %}
                {% endif %}
            </div>

            <a href="/ai" class="mystes-btn mystes-btn-gold mystes-btn-full">View Deal</a>
        </div>

        <script>
        (function() {
            try {
                var raw = {{ item.item_data_json | default('{}', true) | tojson | safe }};
                var d = (typeof raw === 'string') ? JSON.parse(raw) : raw;
                var titleEl = document.getElementById('item-title-{{ item.id }}');
                var subEl = document.getElementById('item-subtitle-{{ item.id }}');
                var vertical = '{{ item.vertical }}';

                if (vertical === 'flight') {
                    var airline = d.airline || d.carrier || '';
                    var origin = d.origin || d.departure || '';
                    var dest = d.destination || d.arrival || '';
                    var route = origin && dest ? (origin + ' \\u2192 ' + dest) : '';
                    titleEl.textContent = airline ? (airline + (route ? ' \\u2014 ' + route : '')) : (route || 'Flight Deal');
                    subEl.textContent = d.departure_date || d.date || '';
                } else if (vertical === 'hotel') {
                    titleEl.textContent = d.hotel_name || d.name || 'Hotel Deal';
                    var loc = d.city || d.location || '';
                    var dates = '';
                    if (d.check_in) dates = d.check_in + (d.check_out ? ' \\u2013 ' + d.check_out : '');
                    subEl.textContent = [loc, dates].filter(Boolean).join(' \\u00B7 ');
                } else if (vertical === 'car') {
                    titleEl.textContent = d.vehicle_name || d.car_name || d.name || 'Car Rental';
                    subEl.textContent = d.location || d.pickup_location || '';
                } else if (vertical === 'activity') {
                    titleEl.textContent = d.activity_name || d.name || d.title || 'Activity';
                    subEl.textContent = d.location || d.city || '';
                }
            } catch(e) {}
        })();
        </script>
        {% endfor %}
    </div>
    {% else %}
    <div class="mystes-empty" style="padding:80px 20px;">
        <div class="collection-empty-icon">&#128203;</div>
        <h3 style="color:var(--text-bright,#f5f5f5);font-size:18px;margin:0 0 8px;">No Items Saved Yet</h3>
        <p style="max-width:380px;margin:0 auto 20px;">Search for flights, hotels, or activities to save them here.</p>
        <a href="/ai" class="mystes-btn mystes-btn-gold">Search MYSTES</a>
    </div>
    {% endif %}
</div>

<script>
async function removeItem(collectionId, itemId) {
    if (!confirm('Remove this item from the collection?')) return;
    try {
        const resp = await fetch('/api/collections/' + collectionId + '/items/' + itemId, { method: 'DELETE' });
        const data = await resp.json();
        if (data.success) {
            window.location.reload();
        } else {
            alert(data.error || 'Failed to remove item');
        }
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function toggleShare(collectionId) {
    const isShared = document.getElementById('share-toggle').checked;
    try {
        const resp = await fetch('/api/collections/' + collectionId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_shared: isShared })
        });
        const data = await resp.json();
        if (data.success) {
            const box = document.getElementById('share-url-box');
            if (isShared && data.share_url) {
                document.getElementById('share-url').value = data.share_url;
                box.style.display = 'flex';
            } else {
                box.style.display = 'none';
            }
        } else {
            document.getElementById('share-toggle').checked = !isShared;
            alert(data.error || 'Failed to update sharing');
        }
    } catch (err) {
        document.getElementById('share-toggle').checked = !isShared;
        alert('Error: ' + err.message);
    }
}

function copyShareLink() {
    const input = document.getElementById('share-url');
    input.select();
    navigator.clipboard.writeText(input.value).then(function() {
        const btn = document.querySelector('.mystes-btn-gold.mystes-btn-sm');
        btn.textContent = 'Copied!';
        setTimeout(function() { btn.textContent = 'Copy'; }, 2000);
    });
}
</script>
"""


# ============================================================
# Route Registration
# ============================================================

def register_collection_routes(app, csrf, limiter):
    """Register all wishlist/collections routes on the Flask app."""
    from server import BASE_TEMPLATE, is_feature_enabled

    # ------------------------------------------------------------------
    # 1. GET /collections — List user's collections
    # ------------------------------------------------------------------

    @app.route("/collections")
    @login_required
    def collections_list():
        """List all collections for the current user."""
        if not is_feature_enabled("wishlist"):
            return redirect(url_for("home"))

        collections = Collection.query.filter_by(
            user_id=current_user.id
        ).order_by(Collection.updated_at.desc()).all()

        return render_template_string(
            BASE_TEMPLATE,
            title="My Collections",
            content=render_template_string(
                COLLECTIONS_LIST_CONTENT,
                collections=collections,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # 2. POST /api/collections — Create a new collection
    # ------------------------------------------------------------------

    @app.route("/api/collections", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_create_collection():
        """Create a new collection."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "error": "Collection name is required"}), 400
        if len(name) > 100:
            return jsonify({"success": False, "error": "Name must be 100 characters or less"}), 400

        try:
            collection = Collection(
                user_id=current_user.id,
                name=name,
            )
            db.session.add(collection)
            db.session.commit()

            logger.info(f"Collection created: id={collection.id}, user={current_user.id}, name={name}")

            return jsonify({
                "success": True,
                "collection_id": collection.id,
                "name": collection.name,
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Create collection error: {e}")
            return jsonify({"success": False, "error": "Failed to create collection"}), 500

    # ------------------------------------------------------------------
    # 3. GET /collections/<id> — Collection detail (owner only)
    # ------------------------------------------------------------------

    @app.route("/collections/<int:collection_id>")
    @login_required
    def collection_detail(collection_id):
        """View a single collection with its items."""
        collection = Collection.query.filter_by(
            id=collection_id, user_id=current_user.id
        ).first()

        if not collection:
            return redirect("/collections")

        items = SavedItem.query.filter_by(
            collection_id=collection.id
        ).order_by(SavedItem.created_at.desc()).all()

        # Build share URL
        share_url = ""
        if collection.is_shared and collection.share_slug:
            share_url = request.url_root.rstrip("/") + "/c/" + collection.share_slug

        return render_template_string(
            BASE_TEMPLATE,
            title=collection.name,
            content=render_template_string(
                COLLECTION_DETAIL_CONTENT,
                collection=collection,
                items=items,
                item_count=len(items),
                share_url=share_url,
                read_only=False,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # 4. GET /c/<slug> — Public shared collection view
    # ------------------------------------------------------------------

    @app.route("/c/<slug>")
    def public_collection(slug):
        """View a shared collection (read-only, no login required)."""
        collection = Collection.query.filter_by(
            share_slug=slug, is_shared=True
        ).first()

        if not collection:
            return redirect("/")

        items = SavedItem.query.filter_by(
            collection_id=collection.id
        ).order_by(SavedItem.created_at.desc()).all()

        # Get owner name for display
        owner = User.query.get(collection.user_id)
        owner_name = owner.name if owner and owner.name else "A MYSTES user"

        share_url = request.url_root.rstrip("/") + "/c/" + slug

        return render_template_string(
            BASE_TEMPLATE,
            title=collection.name + " - Shared Collection",
            content=render_template_string(
                COLLECTION_DETAIL_CONTENT,
                collection=collection,
                items=items,
                item_count=len(items),
                share_url=share_url,
                read_only=True,
                current_user=current_user,
            ),
            current_user=current_user,
        )

    # ------------------------------------------------------------------
    # 5. PUT /api/collections/<id> — Update collection (name, sharing)
    # ------------------------------------------------------------------

    @app.route("/api/collections/<int:collection_id>", methods=["PUT"])
    @csrf.exempt
    @login_required
    def api_update_collection(collection_id):
        """Update a collection's name or sharing status."""
        collection = Collection.query.filter_by(
            id=collection_id, user_id=current_user.id
        ).first()

        if not collection:
            return jsonify({"success": False, "error": "Collection not found"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        try:
            # Update name if provided
            if "name" in data:
                name = (data["name"] or "").strip()
                if name and len(name) <= 100:
                    collection.name = name

            # Update sharing
            if "is_shared" in data:
                is_shared = bool(data["is_shared"])
                collection.is_shared = is_shared

                if is_shared and not collection.share_slug:
                    collection.share_slug = secrets.token_urlsafe(8)

            db.session.commit()

            share_url = ""
            if collection.is_shared and collection.share_slug:
                share_url = request.url_root.rstrip("/") + "/c/" + collection.share_slug

            return jsonify({
                "success": True,
                "collection_id": collection.id,
                "name": collection.name,
                "is_shared": collection.is_shared,
                "share_url": share_url,
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Update collection error: {e}")
            return jsonify({"success": False, "error": "Failed to update collection"}), 500

    # ------------------------------------------------------------------
    # 6. DELETE /api/collections/<id> — Delete collection + items
    # ------------------------------------------------------------------

    @app.route("/api/collections/<int:collection_id>", methods=["DELETE"])
    @csrf.exempt
    @login_required
    def api_delete_collection(collection_id):
        """Delete a collection and all its saved items."""
        collection = Collection.query.filter_by(
            id=collection_id, user_id=current_user.id
        ).first()

        if not collection:
            return jsonify({"success": False, "error": "Collection not found"}), 404

        try:
            # Delete child items first
            SavedItem.query.filter_by(collection_id=collection.id).delete()
            db.session.delete(collection)
            db.session.commit()

            logger.info(f"Collection deleted: id={collection_id}, user={current_user.id}")

            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Delete collection error: {e}")
            return jsonify({"success": False, "error": "Failed to delete collection"}), 500

    # ------------------------------------------------------------------
    # 7. POST /api/collections/<id>/items — Save item to collection
    # ------------------------------------------------------------------

    @app.route("/api/collections/<int:collection_id>/items", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_add_item(collection_id):
        """Add a saved item to a collection."""
        collection = Collection.query.filter_by(
            id=collection_id, user_id=current_user.id
        ).first()

        if not collection:
            return jsonify({"success": False, "error": "Collection not found"}), 404

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        vertical = (data.get("vertical") or "").strip().lower()
        if vertical not in ("flight", "hotel", "car", "activity", "dining"):
            return jsonify({"success": False, "error": "Invalid vertical. Must be flight, hotel, car, activity, or dining."}), 400

        item_data = data.get("item_data_json")
        if isinstance(item_data, dict):
            item_data = json.dumps(item_data)

        price_at_save = data.get("price_at_save")
        if price_at_save is not None:
            try:
                price_at_save = float(price_at_save)
            except (ValueError, TypeError):
                price_at_save = None

        try:
            item = SavedItem(
                user_id=current_user.id,
                collection_id=collection.id,
                vertical=vertical,
                item_data_json=item_data,
                price_at_save=price_at_save,
            )
            db.session.add(item)
            db.session.commit()

            logger.info(f"Item saved: id={item.id}, collection={collection_id}, vertical={vertical}")

            return jsonify({
                "success": True,
                "item_id": item.id,
                "collection_id": collection.id,
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Add item error: {e}")
            return jsonify({"success": False, "error": "Failed to save item"}), 500

    # ------------------------------------------------------------------
    # 8. DELETE /api/collections/<id>/items/<item_id> — Remove item
    # ------------------------------------------------------------------

    @app.route("/api/collections/<int:collection_id>/items/<int:item_id>", methods=["DELETE"])
    @csrf.exempt
    @login_required
    def api_remove_item(collection_id, item_id):
        """Remove a saved item from a collection."""
        collection = Collection.query.filter_by(
            id=collection_id, user_id=current_user.id
        ).first()

        if not collection:
            return jsonify({"success": False, "error": "Collection not found"}), 404

        item = SavedItem.query.filter_by(
            id=item_id, collection_id=collection.id
        ).first()

        if not item:
            return jsonify({"success": False, "error": "Item not found"}), 404

        try:
            db.session.delete(item)
            db.session.commit()

            logger.info(f"Item removed: id={item_id}, collection={collection_id}")

            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            logger.error(f"Remove item error: {e}")
            return jsonify({"success": False, "error": "Failed to remove item"}), 500

    # ------------------------------------------------------------------
    # 9. POST /api/save-item — Quick-save to default "Favorites"
    # ------------------------------------------------------------------

    @app.route("/api/save-item", methods=["POST"])
    @csrf.exempt
    @login_required
    def api_quick_save_item():
        """Quick-save an item to the user's default Favorites collection."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        vertical = (data.get("vertical") or "").strip().lower()
        if vertical not in ("flight", "hotel", "car", "activity", "dining"):
            return jsonify({"success": False, "error": "Invalid vertical"}), 400

        item_data = data.get("item_data_json")
        if isinstance(item_data, dict):
            item_data = json.dumps(item_data)

        price_at_save = data.get("price_at_save")
        if price_at_save is not None:
            try:
                price_at_save = float(price_at_save)
            except (ValueError, TypeError):
                price_at_save = None

        try:
            # Find or create the "Favorites" collection
            favorites = Collection.query.filter_by(
                user_id=current_user.id, name="Favorites"
            ).first()

            if not favorites:
                favorites = Collection(
                    user_id=current_user.id,
                    name="Favorites",
                )
                db.session.add(favorites)
                db.session.flush()

            item = SavedItem(
                user_id=current_user.id,
                collection_id=favorites.id,
                vertical=vertical,
                item_data_json=item_data,
                price_at_save=price_at_save,
            )
            db.session.add(item)
            db.session.commit()

            logger.info(f"Quick-save: id={item.id}, favorites={favorites.id}, vertical={vertical}")

            return jsonify({
                "success": True,
                "item_id": item.id,
                "collection_id": favorites.id,
                "collection_name": "Favorites",
            })
        except Exception as e:
            db.session.rollback()
            logger.error(f"Quick-save error: {e}")
            return jsonify({"success": False, "error": "Failed to save item"}), 500
